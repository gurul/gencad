import { createScreenSpaceLineStrip } from "@text-to-cad/core/common/renderEdges.js";
import {
  ANNOTATION_RENDER_ORDER, disposeAnnotationObject, placeAnnotationObject, annotationDocument, annotationMarkObject, annotationObjectShown as shown, annotationPartObjects
} from "@text-to-cad/core/common/annotation.js";
import { markPoints } from "../../../../annotation/geometry.js";
import { requestSceneFrame } from "../../viewport/sceneFrames.js";

// The annotation in the model: each mark Annotate puts down (`annotation/geometry.js`), drawn over the view
// as the camera stood then, projected into 3D so it stays where it was drawn from every angle — the
// way a grease pencil's "surface" strokes do. Each mark belongs to the part most of it lies on (`part`),
// in that part's own frame, so whatever moves the part — spreading the model apart, posing it —
// carries it, Clip cuts it and hiding the part
// hides it; ink over empty space carries on in the air at the model's depth beside it. A mark drawn
// in space (`placement: "space"`) lies instead on a plane facing the view in front of the model,
// on no part. What lies under the marks is read from one render of the parts' depth, not a ray per point. The projected
// ink is plain data (`AnnotationItem`), kept across scene rebuilds; `mountAnnotations` draws it in a viewer runtime
// and follows its parts each frame.

/**
 * A mark as Annotate keeps it: an annotation mark (`@text-to-cad/core/common/annotation.js`, the shape a prompt's
 * annotation file and a snapshot job read), its points a Float32Array, with `frame`: where its part was
 * in the world when it was drawn (a 4×4 matrix, column order), for the annotation file's `parts`.
 * @typedef {import("@text-to-cad/core/common/annotation.js").AnnotationMark & { points: Float32Array, frame?: number[] }} AnnotationItem
 */

// What a ray from the view can land on: the model's part meshes, as a pick sees them.
function pickTargets(runtime) {
  const targets = [];
  runtime.modelGroup?.traverse(object => {
    if ((object.isMesh || object.isInstancedMesh) && (object.userData?.partId != null || Array.isArray(object.userData?.partIds))) targets.push(object);
  });
  return targets;
}
const partIdOf = hit => (Array.isArray(hit.object.userData?.partIds) && hit.instanceId != null
  ? hit.object.userData.partIds[hit.instanceId] : hit.object.userData?.partId) ?? null;
// A part's own object (not an instanced draw of several): what its ink hangs on.
export const partObjects = runtime => annotationPartObjects(runtime.modelGroup);

// A fill's triangles, split until none has an edge longer than `limit` pixels — every one at once,
// so neighbours never meet at a crack — for the fill to follow a curved surface as a stroke does.
// The outline's points come first, in order; the rest are inside.
const FILL_SEGMENT_PX = 12;
function subdivideArea(THREE, outline, limit = FILL_SEGMENT_PX) {
  const points = outline.map(point => ({ x: point.x, y: point.y }));
  let triangles = THREE.ShapeUtils.triangulateShape(outline.map(point => new THREE.Vector2(point.x, point.y)), []);
  const middles = new Map();
  const middle = (a, b) => {
    const key = a < b ? `${a}|${b}` : `${b}|${a}`;
    if (!middles.has(key)) { points.push({ x: (points[a].x + points[b].x) / 2, y: (points[a].y + points[b].y) / 2 }); middles.set(key, points.length - 1); }
    return middles.get(key);
  };
  const long = ([a, b, c]) => Math.max(...[[a, b], [b, c], [c, a]].map(([u, v]) => Math.hypot(points[u].x - points[v].x, points[u].y - points[v].y))) > limit;
  for (let pass = 0; pass < 6 && triangles.some(long); pass += 1) {
    triangles = triangles.flatMap(([a, b, c]) => {
      const ab = middle(a, b), bc = middle(b, c), ca = middle(c, a);
      return [[a, ab, ca], [ab, b, bc], [ca, bc, c], [ab, bc, ca]];
    });
  }
  return { points, index: triangles.flat() };
}

// Ink stands off what it lies on, toward the eye, by this many screen pixels: clear of the face
// without leaving it. A text mark, flat over what it covers, by four times as much.
const LIFT_PX = 2;
// A stroke stands in front of everything within this many pixels of its line, beyond half its width,
// so nothing it was drawn over cuts through it.
const COVER_PX = 2;

// The parts' depth shader: each pixel's depth along the view, the object drawn there (1-based) and
// its instance — the parts as the view shows them, clipped as they are.
const SURFACE_VERTEX = `#include <common>
#include <clipping_planes_pars_vertex>
varying float vInkDepth;
flat varying float vInkInstance;
void main() {
#include <begin_vertex>
#include <project_vertex>
#include <clipping_planes_vertex>
  vInkDepth = -mvPosition.z;
#ifdef USE_INSTANCING
  vInkInstance = float(gl_InstanceID);
#else
  vInkInstance = 0.0;
#endif
}`;
const SURFACE_FRAGMENT = `#include <clipping_planes_pars_fragment>
uniform float annotationObject;
varying float vInkDepth;
flat varying float vInkInstance;
void main() {
#include <clipping_planes_fragment>
  gl_FragColor = vec4(vInkDepth, annotationObject, vInkInstance, 1.0);
}`;
// One per renderer, kept: a material disposed with each stroke would take its program with it.
const surfaceMaterials = new WeakMap();

// The parts' surface over `box` (CSS pixels of the viewport, `size`) in one render of the parts
// alone, read back: `null` where the renderer cannot draw to floats.
function renderSurface(runtime, targets, box, size) {
  const { THREE, renderer, scene, camera } = runtime;
  if (!renderer?.readRenderTargetPixels || !renderer.capabilities?.isWebGL2 || !renderer.extensions?.has?.("EXT_color_buffer_float")) return null;
  let material = surfaceMaterials.get(renderer);
  if (!material) {
    material = new THREE.ShaderMaterial({ uniforms: { annotationObject: { value: 0 } }, vertexShader: SURFACE_VERTEX, fragmentShader: SURFACE_FRAGMENT,
      side: THREE.DoubleSide, clipping: true });
    surfaceMaterials.set(renderer, material);
  }
  const index = new Map(targets.map((object, position) => [object, position + 1]));
  material.onBeforeRender = (_renderer, _scene, _camera, _geometry, object) => {
    material.uniforms.annotationObject.value = index.get(object) || 0;
    material.uniformsNeedUpdate = true;
  };
  material.clippingPlanes = Array.isArray(runtime.activeClipPlanes) && runtime.activeClipPlanes.length ? runtime.activeClipPlanes : null;
  const target = new THREE.WebGLRenderTarget(box.w, box.h, { type: THREE.FloatType, minFilter: THREE.NearestFilter, magFilter: THREE.NearestFilter });
  // Only the parts are drawn: the rest of the scene (edges, ink, the floor, caps) steps aside.
  const hidden = [];
  scene.traverse(object => {
    if (object.visible && (object.isMesh || object.isLine || object.isPoints || object.isSprite) && !index.has(object)) { object.visible = false; hidden.push(object); }
  });
  const kept = { background: scene.background, fog: scene.fog, overrideMaterial: scene.overrideMaterial, onBeforeRender: scene.onBeforeRender, onAfterRender: scene.onAfterRender };
  const renderTarget = renderer.getRenderTarget(), clearColor = renderer.getClearColor(new THREE.Color()), clearAlpha = renderer.getClearAlpha();
  const shadows = renderer.shadowMap.autoUpdate, xr = renderer.xr?.enabled === true;
  const view = camera.view?.enabled ? { ...camera.view } : null;
  const pixels = new Float32Array(box.w * box.h * 4);
  try {
    Object.assign(scene, { background: null, fog: null, overrideMaterial: material, onBeforeRender() {}, onAfterRender() {} });
    renderer.shadowMap.autoUpdate = false;
    if (renderer.xr) renderer.xr.enabled = false;
    camera.setViewOffset(size.width, size.height, box.x, box.y, box.w, box.h);
    camera.updateProjectionMatrix();
    renderer.setRenderTarget(target);
    renderer.setClearColor(0x000000, 0);
    renderer.clear();
    renderer.render(scene, camera);
    renderer.readRenderTargetPixels(target, 0, 0, box.w, box.h, pixels);
  } finally {
    if (view) camera.setViewOffset(view.fullWidth, view.fullHeight, view.offsetX, view.offsetY, view.width, view.height);
    else camera.clearViewOffset();
    camera.updateProjectionMatrix();
    renderer.setRenderTarget(renderTarget);
    renderer.setClearColor(clearColor, clearAlpha);
    renderer.shadowMap.autoUpdate = shadows;
    if (renderer.xr) renderer.xr.enabled = xr;
    Object.assign(scene, kept);
    for (const object of hidden) object.visible = true;
    target.dispose();
  }
  // Read back bottom row first: turned the screen's way up.
  const depth = new Float32Array(box.w * box.h).fill(Infinity), owner = new Int32Array(box.w * box.h), instance = new Int32Array(box.w * box.h);
  for (let row = 0; row < box.h; row += 1) {
    for (let column = 0; column < box.w; column += 1) {
      const from = ((box.h - 1 - row) * box.w + column) * 4, to = row * box.w + column;
      if (!(pixels[from + 3] > 0) || !(pixels[from + 1] > 0)) continue;
      depth[to] = pixels[from];
      owner[to] = Math.round(pixels[from + 1]);
      instance[to] = Math.round(pixels[from + 2]);
    }
  }
  return { depth, owner, instance };
}

// The same, without a GPU: a ray through each pixel's centre.
function castSurface(runtime, targets, box, size, depthOf) {
  const { THREE, camera } = runtime;
  const caster = new THREE.Raycaster(), ndc = new THREE.Vector2();
  const planes = Array.isArray(runtime.activeClipPlanes) ? runtime.activeClipPlanes : [];
  const index = new Map(targets.map((object, position) => [object, position + 1]));
  const depth = new Float32Array(box.w * box.h).fill(Infinity), owner = new Int32Array(box.w * box.h), instance = new Int32Array(box.w * box.h);
  for (let row = 0; row < box.h; row += 1) {
    for (let column = 0; column < box.w; column += 1) {
      ndc.set(((box.x + column + 0.5) / size.width) * 2 - 1, -((box.y + row + 0.5) / size.height) * 2 + 1);
      caster.setFromCamera(ndc, camera);
      const hit = caster.intersectObjects(targets, false)
        .find(candidate => shown(candidate.object) && planes.every(plane => plane.distanceToPoint(candidate.point) >= 0) && partIdOf(candidate) != null);
      if (!hit) continue;
      const at = row * box.w + column;
      depth[at] = depthOf(hit.point);
      owner[at] = index.get(hit.object);
      instance[at] = hit.instanceId ?? 0;
    }
  }
  return { depth, owner, instance };
}

// What the view shows of the parts around a set of screen points: the depth and the part at a point,
// and the nearest depth along a stretch of the screen.
function surfaceUnder(runtime, targets, points, pad, size, depthOf) {
  let left = Infinity, top = Infinity, right = -Infinity, bottom = -Infinity;
  for (const { x, y } of points) { left = Math.min(left, x); top = Math.min(top, y); right = Math.max(right, x); bottom = Math.max(bottom, y); }
  const x = Math.max(0, Math.floor(left - pad)), y = Math.max(0, Math.floor(top - pad));
  const box = { x, y, w: Math.min(Math.ceil(size.width), Math.ceil(right + pad) + 1) - x, h: Math.min(Math.ceil(size.height), Math.ceil(bottom + pad) + 1) - y };
  const empty = { partAt: () => null, nearest: () => Infinity };
  if (!(box.w > 0) || !(box.h > 0) || !targets.length) return empty;
  const { depth, owner, instance } = renderSurface(runtime, targets, box, size) ?? castSurface(runtime, targets, box, size, depthOf);
  const cell = (px, py) => {
    const column = Math.floor(px) - box.x, row = Math.floor(py) - box.y;
    return column < 0 || row < 0 || column >= box.w || row >= box.h ? -1 : row * box.w + column;
  };
  return {
    partAt(point) {
      const at = cell(point.x, point.y);
      if (at < 0 || !owner[at]) return null;
      return partIdOf({ object: targets[owner[at] - 1], instanceId: instance[at] });
    },
    // The nearest depth within `radius` pixels of the line from `a` to `b` (Infinity: nothing there).
    nearest(a, b, radius) {
      let best = Infinity;
      const steps = Math.max(1, Math.ceil(Math.hypot(b.x - a.x, b.y - a.y)));
      const reach = Math.ceil(radius);
      for (let step = 0; step <= steps; step += 1) {
        const cx = a.x + (b.x - a.x) * step / steps, cy = a.y + (b.y - a.y) * step / steps;
        for (let dy = -reach; dy <= reach; dy += 1) {
          for (let dx = -reach; dx <= reach; dx += 1) {
            const at = cell(cx + dx, cy + dy);
            if (at >= 0 && depth[at] < best) best = depth[at];
          }
        }
      }
      return best;
    },
  };
}

// Depths along a stroke where some are unknown (Infinity: over nothing), from the known ones either
// side of them, so a stroke leaving the model carries on from where it left it.
function bridgeDepths(depths, fallback) {
  const known = depths.map((depth, index) => (Number.isFinite(depth) ? index : -1)).filter(index => index >= 0);
  if (!known.length) return depths.map(() => fallback);
  return depths.map((depth, index) => {
    if (Number.isFinite(depth)) return depth;
    const after = known.find(at => at > index), before = known.findLast(at => at < index);
    if (before == null) return depths[after];
    if (after == null) return depths[before];
    return depths[before] + (depths[after] - depths[before]) * (index - before) / (after - before);
  });
}

/**
 * The marks of an annotation projected into the model from the camera they were drawn under.
 *
 * Each point stays on the ray through where it was drawn, so from that view the ink is exactly what
 * was drawn; its depth along the ray is the model's there. A stroke lies over the nearest of what is
 * within a few pixels of its line, so it is never cut by what it was drawn over, and carries on in
 * the air from the model's depth where it leaves it. A fill lies on the surface when all of it is
 * over the model, else whole on a sheet facing the view in front of what it covers; a text mark
 * stands in front of what it covers. A mark belongs to the part most of it lies on; marks drawn as
 * one thing (`group`: an arrow's line and its head) to the part most of them all lies on, so they
 * never come apart.
 *
 * A mark drawn in space (`placement: "space"`) lies whole on the plane facing the view just in front
 * of the model's bounds, so nothing of the model hides it from where it was drawn, in world
 * coordinates on no part. Marks all in space need no render of the parts.
 *
 * @param {object} runtime  The viewer runtime (`THREE`, `camera`, `controls`, `modelGroup`, `renderer`, `scene`, `activeClipPlanes`).
 * @param {import("../../../../annotation/geometry.js").ScreenMark[]} marks
 * @param {{ width: number, height: number }} size  The viewport's CSS size, which the marks' pixels are of.
 * @returns {AnnotationItem[]}
 */
export function projectAnnotations(runtime, marks, size) {
  const { THREE, camera } = runtime;
  const { width, height } = size;
  if (!THREE || !camera || !(width > 0) || !(height > 0) || !marks.length) return [];
  camera.updateMatrixWorld();
  const targets = pickTargets(runtime);
  const eye = new THREE.Vector3().setFromMatrixPosition(camera.matrixWorld);
  const view = new THREE.Vector3(); camera.getWorldDirection(view);
  const depthOf = point => point.clone().sub(eye).dot(view);
  // One screen pixel's size at a depth.
  const pixel = depth => (camera.isOrthographicCamera
    ? (camera.top - camera.bottom) / (camera.zoom * height)
    : 2 * Math.max(depth, camera.near) * Math.tan(THREE.MathUtils.degToRad(camera.getEffectiveFOV()) / 2) / height);
  const caster = new THREE.Raycaster(), ndc = new THREE.Vector2();
  const at = ({ x, y }, depth) => {
    ndc.set((x / width) * 2 - 1, -(y / height) * 2 + 1);
    caster.setFromCamera(ndc, camera);
    const { origin, direction } = caster.ray;
    const along = direction.dot(view);
    const t = Math.abs(along) < 1e-9 ? 0 : (depth - origin.clone().sub(eye).dot(view)) / along;
    return origin.clone().addScaledVector(direction, t);
  };
  const lifted = (depth, px = LIFT_PX) => depth - px * pixel(depth);
  const fallback = runtime.controls?.target ? depthOf(runtime.controls.target) : 0;

  const shaped = marks.map(mark => {
    const area = mark.kind === "area" ? subdivideArea(THREE, mark.outline) : null;
    return { mark, area, points: area ? area.points : markPoints(mark), space: mark.placement === "space" };
  });
  // The parts are rendered only under the marks that lie on them.
  const onModel = shaped.filter(({ space }) => !space);
  const reach = Math.max(FILL_SEGMENT_PX, ...onModel.map(({ mark }) => (mark.kind === "stroke" ? mark.width * Math.max(1, ...(mark.widths || [1])) / 2 + COVER_PX : 0)));
  const surface = onModel.length ? surfaceUnder(runtime, targets, onModel.flatMap(({ points }) => points), reach + 1, size, depthOf) : null;
  const objects = partObjects(runtime);
  // In space: the plane facing the view just in front of the model's bounds, nothing to stand off.
  let spaceDepth = null;
  const inSpace = () => {
    if (spaceDepth != null) return spaceDepth;
    const box = new THREE.Box3().setFromObject(runtime.modelGroup ?? new THREE.Group());
    const corners = box.isEmpty() ? [] : [0, 1, 2, 3, 4, 5, 6, 7].map(index => new THREE.Vector3(
      index & 1 ? box.max.x : box.min.x, index & 2 ? box.max.y : box.min.y, index & 4 ? box.max.z : box.min.z));
    const front = corners.length ? Math.min(...corners.map(depthOf)) : fallback;
    spaceDepth = camera.isPerspectiveCamera ? Math.max(front, camera.near * 2) : front;
    spaceDepth = lifted(spaceDepth);
    return spaceDepth;
  };

  // What each mark lies on; a group's marks pool theirs.
  const tallies = shaped.map(({ points, space }) => {
    const tally = new Map();
    if (!space) for (const point of points) { const id = surface.partAt(point); if (id != null) tally.set(String(id), (tally.get(String(id)) || 0) + 1); }
    return tally;
  });
  const pooled = new Map();
  shaped.forEach(({ mark }, index) => {
    if (!mark.group) return;
    const pool = pooled.get(mark.group) ?? new Map();
    for (const [id, count] of tallies[index]) pool.set(id, (pool.get(id) || 0) + count);
    pooled.set(mark.group, pool);
  });
  const most = tally => [...tally.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] ?? null;

  return shaped.map(({ mark, area, points, space }, index) => {
    // Its part: the one most of it (or of its group) lies on; none for a mark in space.
    const tally = tallies[index];
    const partId = space ? null : most(mark.group ? pooled.get(mark.group) : tally);
    let depths;
    if (space) depths = points.map(() => inSpace());
    else if (mark.kind === "stroke") {
      const radius = index => mark.width * (mark.widths?.[index] ?? 1) / 2 + COVER_PX;
      const span = points.slice(1).map((point, index) => surface.nearest(points[index], point, Math.max(radius(index), radius(index + 1))));
      const near = points.length === 1 ? [surface.nearest(points[0], points[0], radius(0))]
        : points.map((_, index) => Math.min(span[index - 1] ?? Infinity, span[index] ?? Infinity));
      depths = bridgeDepths(near, fallback).map(depth => lifted(depth));
    } else if (mark.kind === "area") {
      const near = points.map(point => surface.nearest(point, point, FILL_SEGMENT_PX / 2));
      const front = Math.min(...near);
      depths = near.every(Number.isFinite) ? near.map(depth => lifted(depth))
        : points.map(() => lifted(Number.isFinite(front) ? front : fallback));
    } else {
      // A text mark: in front of all it covers, sampled across its face.
      const [a, b, , d] = mark.corners;
      let front = Infinity;
      for (let v = 0; v <= 1; v += 1 / Math.max(1, Math.ceil(Math.hypot(d.x - a.x, d.y - a.y)))) {
        const from = { x: a.x + (d.x - a.x) * v, y: a.y + (d.y - a.y) * v };
        front = Math.min(front, surface.nearest(from, { x: from.x + b.x - a.x, y: from.y + b.y - a.y }, 0));
      }
      depths = points.map(() => lifted(Number.isFinite(front) ? front : fallback, LIFT_PX * 4));
    }
    const frame = partId != null ? objects.get(partId) : null;
    if (frame) frame.updateWorldMatrix(true, false);
    const toLocal = frame ? new THREE.Matrix4().copy(frame.matrixWorld).invert() : null;
    const positions = new Float32Array(points.length * 3);
    points.forEach((point, index) => { const world = at(point, depths[index]); (toLocal ? world.applyMatrix4(toLocal) : world).toArray(positions, index * 3); });
    // What it was drawn over, most first.
    const touches = [...tally.entries()].sort((a, b) => b[1] - a[1]).map(([part]) => ({ part }));
    const item = { id: mark.id, kind: mark.kind, part: frame ? partId : null, placement: space ? "space" : "surface", points: positions,
      color: mark.color, ...(frame ? { frame: frame.matrixWorld.toArray() } : {}), ...(mark.group ? { group: mark.group } : {}),
      ...(mark.view ? { view: mark.view } : {}), touches };
    if (mark.kind === "stroke") Object.assign(item, { width: mark.width, opacity: mark.opacity, dash: mark.dash, closed: mark.closed,
      ...(mark.widths ? { widths: mark.widths } : {}) });
    else if (mark.kind === "area") Object.assign(item, { opacity: mark.opacity, triangles: area.index, outline: mark.outline.length });
    else Object.assign(item, { text: mark.text, fontPx: mark.fontPx });
    return item;
  });
}

/**
 * The annotation as an annotation file says it (`@text-to-cad/core/common/annotation.js`): its marks, and where
 * each part they hang on was when they were drawn.
 * @param {readonly AnnotationItem[]} items
 * @param {string} [units]
 */
export function annotationDocumentOf(items, units = "mm") {
  const placements = new Map();
  for (const item of items) if (item.part != null && item.frame && !placements.has(item.part)) placements.set(item.part, item.frame);
  return annotationDocument({ units, placements, marks: items.map(({ frame: _frame, ...mark }) => mark) });
}

/** Each item's points where they are in the world now: its part's frame as the scene has it. */
export function annotationWorldPoints(runtime, item, parts = partObjects(runtime)) {
  const { THREE } = runtime;
  const part = item.part != null ? parts.get(String(item.part)) : null;
  if (part) part.updateWorldMatrix(true, false);
  const points = [];
  for (let index = 0; index < item.points.length; index += 3) {
    const point = new THREE.Vector3().fromArray(item.points, index);
    points.push(part ? point.applyMatrix4(part.matrixWorld) : point);
  }
  return points;
}

/**
 * The ink as it falls on the screen now (`annotation/geometry.js`'s `ScreenAnnotation`): to hit-test with
 * the eraser and Select, and to bound a fill. Ink behind the eye, or on a hidden part, is not there.
 */
export function annotationsOnScreen(runtime, items, { width, height }) {
  const { THREE, camera } = runtime;
  camera.updateMatrixWorld();
  const parts = partObjects(runtime);
  const eye = new THREE.Vector3().setFromMatrixPosition(camera.matrixWorld);
  const view = new THREE.Vector3(); camera.getWorldDirection(view);
  return items.flatMap(item => {
    const part = item.part != null ? parts.get(String(item.part)) : null;
    if (item.part != null && (!part || !shown(part))) return [];
    const all = annotationWorldPoints(runtime, item, parts);
    // A fill's outline: its first points (the rest are inside it).
    const world = item.kind === "area" && item.outline ? all.slice(0, item.outline) : all;
    if (world.some(point => point.clone().sub(eye).dot(view) <= 0)) return [];
    const points = world.map(point => {
      const ndc = point.clone().project(camera);
      return { x: ((ndc.x + 1) / 2) * width, y: ((1 - ndc.y) / 2) * height };
    });
    return [{ id: item.id, kind: item.kind, points, closed: Boolean(item.closed), width: Math.max(...(item.widths || [1])) * (item.width || 0) }];
  });
}

// What Select has picked is haloed: a wider line in the selection's blue behind the ink, along a
// stroke, round a fill's outline or a text mark's box; what the pointer rests on, a fainter one.
const SELECTION_COLOR = "#2979ff";
const HALO_PX = 6;
const PICKED_OPACITY = 0.5;
const HOVERED_OPACITY = 0.25;
function haloObject(runtime, item, lineScale, opacity) {
  const outline = item.kind === "stroke" ? item.points
    : item.points.subarray(0, 3 * (item.kind === "area" ? item.outline ?? item.points.length / 3 : 4));
  const closed = item.kind !== "stroke" || item.closed;
  const points = closed && item.kind !== "stroke" ? Float32Array.from([...outline, ...outline.subarray(0, 3)]) : outline;
  const width = item.kind === "stroke" ? item.width * Math.max(1, ...(item.widths || [1])) : 2;
  const halo = createScreenSpaceLineStrip(runtime, points, { color: SELECTION_COLOR, opacity,
    lineWidth: (width + HALO_PX) * lineScale, renderOrder: ANNOTATION_RENDER_ORDER - 1, depthTest: true, depthWrite: false });
  if (halo) {
    halo.matrixAutoUpdate = false;
    halo.matrixWorldAutoUpdate = false;
    halo.frustumCulled = false;
    halo.userData.haloOpacity = opacity;
  }
  return halo;
}

/**
 * Draws projected ink in a viewer runtime until `dispose()`: `update(items, selected)` draws a
 * annotation's ink as it is now, making objects only for items it has not drawn yet and dropping those
 * it no longer has (an item is never changed in place: a changed one is a new item), and halos the
 * ink Select has picked (`selected`, ids) and, fainter, what the pointer rests on (`hovered`). Every frame, before anything is
 * drawn, each mark takes its part's place (its frame as the scene has it then: spread apart, posed),
 * hides with it, and takes the clip planes the model has. A part rebuilt under it is found again by id.
 *
 * @param {object} runtime
 * @returns {{ group: import("three").Group, update(items: AnnotationItem[], selected?: readonly string[], hovered?: readonly string[]): void, dispose(): void }}
 */
export function mountAnnotations(runtime) {
  const { THREE, scene } = runtime;
  // Ink casts no shadow: a frame that keeps the shadow maps it has (`viewport/sceneFrames.js`).
  const redraw = () => requestSceneFrame(runtime, false);
  const group = new THREE.Group();
  group.name = "annotations";
  scene.add(group);
  const radius = Number(runtime.modelRadius) || 1;
  // A stroke's width is in CSS pixels; the line's in device pixels.
  const lineScale = Number(runtime.renderer?.getPixelRatio?.()) || 1;
  let entries = new Map();
  let halos = new Map();
  let parts = partObjects(runtime);
  const attached = object => { for (let node = object; node; node = node.parent) if (node === scene) return true; return false; };
  const follow = () => {
    // A scene rebuilt under the ink has new part objects: find them again.
    if ([...parts.values()].some(object => !attached(object))) parts = partObjects(runtime);
    const planes = Array.isArray(runtime.activeClipPlanes) ? runtime.activeClipPlanes : [];
    for (const [item, object] of [...entries, ...halos]) {
      // A part the scene has lost (it is rebuilding) hides its ink until it is back.
      placeAnnotationObject(object, item, parts, { planes, visible: item.part == null || parts.has(String(item.part)) });
    }
  };
  let previous = scene.onBeforeRender;
  let ran = false;
  const hook = function inkBeforeRender(...args) { ran = true; follow(); return previous?.apply(this, args); };
  const install = () => { previous = scene.onBeforeRender; scene.onBeforeRender = hook; };
  install();
  // Another owner of the scene's hook (the photographic studio) puts back whatever it found when it
  // leaves, which can drop this one. A sentinel drawn every frame (writing nothing) checks that the
  // hook ran for this frame — whoever wraps whom — and, if it did not, puts it back for the next.
  const sentinel = new THREE.Mesh(new THREE.BufferGeometry().setAttribute("position", new THREE.BufferAttribute(new Float32Array(9), 3)),
    new THREE.MeshBasicMaterial({ colorWrite: false, depthWrite: false, depthTest: false }));
  sentinel.frustumCulled = false;
  sentinel.renderOrder = -1e9;
  sentinel.onBeforeRender = () => {
    if (!ran) { install(); redraw(); }
    ran = false;
  };
  group.add(sentinel);
  const release = disposeAnnotationObject;
  return {
    group,
    update(items, selected = [], hovered = []) {
      const next = new Map();
      for (const item of items) {
        let object = entries.get(item);
        if (!object) {
          object = annotationMarkObject(runtime, item, { radius, lineScale });
          if (!object) continue;
          group.add(object);
        }
        next.set(item, object);
      }
      for (const [item, object] of entries) if (!next.has(item)) release(object);
      entries = next;
      const picked = new Set(selected);
      const lit = new Set(hovered);
      const nextHalos = new Map();
      for (const item of items) {
        const opacity = picked.has(item.id) ? PICKED_OPACITY : lit.has(item.id) ? HOVERED_OPACITY : 0;
        if (!opacity) continue;
        let halo = halos.get(item);
        if (halo && halo.userData.haloOpacity !== opacity) { release(halo); halos.delete(item); halo = null; }
        halo ??= haloObject(runtime, item, lineScale, opacity);
        if (!halo) continue;
        if (!halo.parent) group.add(halo);
        nextHalos.set(item, halo);
      }
      for (const [item, halo] of halos) if (!nextHalos.has(item)) release(halo);
      halos = nextHalos;
      follow();
      redraw();
    },
    dispose() {
      if (scene.onBeforeRender === hook) scene.onBeforeRender = previous;
      group.removeFromParent();
      sentinel.geometry.dispose();
      sentinel.material.dispose();
      for (const object of [...entries.values(), ...halos.values()]) release(object);
      entries = new Map();
      halos = new Map();
      redraw();
    },
  };
}
