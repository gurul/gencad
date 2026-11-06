import { createScreenSpaceLineStrip } from "./renderEdges.js";

// An annotation: ink drawn over a model in the CAD Viewer's Annotate tool, in 3D. The viewer draws it live
// and writes it with a prompt; a snapshot job draws it over the model it renders (`job.annotation`),
// with this same code, so what an agent renders is what the person drew.
//
// Each mark is fixed to one part (`part`, an occurrence id) and its points are in that part's own
// frame, so it follows the part wherever the scene puts it — exploded, posed — hides when the part
// is hidden and is cut by the same clip planes. A part the scene no longer has falls back to where
// it was when the annotation was made (`parts[id].placement`). A mark on no part (`part: null`) is in
// model coordinates and stays where it was drawn.

/**
 * @typedef {"stroke" | "area" | "text"} AnnotationMarkKind
 * @typedef {{
 *   id: string, kind: AnnotationMarkKind, part: string | null, placement?: "surface" | "space", view?: string,
 *   points: ArrayLike<number>, color: string, opacity?: number,
 *   width?: number, widths?: ArrayLike<number>, dash?: "solid" | "dashed" | "dotted", closed?: boolean, group?: string,
 *   outline?: number, triangles?: ArrayLike<number>,
 *   text?: string, fontPx?: number,
 *   touches?: { part: string }[]
 * }} AnnotationMark
 *   `points`: x, y, z triples, in the frame of `part` (model coordinates for a mark on no part). A
 *   stroke's are its line; an area's (a fill) its outline (the first `outline`) then the points inside
 *   it its `triangles` index; a text mark's its label's four corners. `width`: a stroke's thickness in
 *   screen pixels, at any zoom; `widths`: the pen's, each point's share of it. `fontPx`: a text mark's
 *   size on screen as it was written. `placement`: drawn on the model, or in space. `view`: the label
 *   of the view it was drawn in. `touches`: the parts under it as it was drawn.
 * @typedef {{ units: string, parts: Record<string, { placement: number[] }>, marks: AnnotationMark[] }} Annotation
 *   `parts[id].placement`: where the part was in the model when the annotation was made, a 4×4 matrix
 *   in column order.
 */

export const ANNOTATION_MARK_KINDS = Object.freeze(["stroke", "area", "text"]);
const DASHES = new Set(["solid", "dashed", "dotted"]);
const PLACEMENTS = new Set(["surface", "space"]);
const COLOR = /^#[0-9a-f]{6}$/i;
// A capture's ink is as heavy against its height as it was on a viewer this tall.
export const ANNOTATION_REFERENCE_HEIGHT_PX = 900;
// Ink is drawn after the model and everything that marks it (a highlighted or ghosted part draws at
// 23–30): it writes no depth, so a part drawn after it would paint over it. Its own depth test still
// hides it behind the model.
export const ANNOTATION_RENDER_ORDER = 40;

const fail = message => { throw new Error(`annotation: ${message}`); };
const numbers = (value, label) => {
  if (!(Array.isArray(value) || ArrayBuffer.isView(value)) || !Array.from(value).every(Number.isFinite)) fail(`${label} must be an array of numbers`);
  return Array.from(value);
};

/**
 * An annotation as it is read from a file or a job: checked field by field, each refusal naming what is
 * wrong. Unknown fields are refused too, so a misspelt one never passes for a default.
 * @param {unknown} raw
 * @returns {Annotation}
 */
export function normalizeAnnotation(raw) {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) fail("an annotation is an object with units, parts and marks");
  for (const key of Object.keys(raw)) if (!["units", "parts", "marks"].includes(key)) fail(`unknown field "${key}"`);
  const units = String(raw.units ?? "mm");
  const parts = {};
  for (const [id, part] of Object.entries(raw.parts ?? {})) {
    const placement = numbers(part?.placement, `parts.${id}.placement`);
    if (placement.length !== 16) fail(`parts.${id}.placement must be a 4×4 matrix of 16 numbers`);
    parts[id] = { placement };
  }
  if (!Array.isArray(raw.marks)) fail("marks must be an array");
  const ids = new Set();
  const marks = raw.marks.map((mark, index) => {
    const at = `marks[${index}]`;
    if (!mark || typeof mark !== "object") fail(`${at} must be an object`);
    for (const key of Object.keys(mark)) {
      if (!["id", "kind", "part", "placement", "view", "points", "color", "opacity", "width", "widths", "dash", "closed", "group",
        "outline", "triangles", "text", "fontPx", "touches"].includes(key)) fail(`${at}: unknown field "${key}"`);
    }
    const id = String(mark.id ?? "");
    if (!id || ids.has(id)) fail(`${at}.id must be a unique, non-empty string`);
    ids.add(id);
    if (!ANNOTATION_MARK_KINDS.includes(mark.kind)) fail(`${at}.kind must be one of ${ANNOTATION_MARK_KINDS.join(", ")}`);
    if (mark.part != null && typeof mark.part !== "string") fail(`${at}.part must be an occurrence id or null`);
    if (mark.placement != null && !PLACEMENTS.has(mark.placement)) fail(`${at}.placement must be "surface" or "space"`);
    if (!COLOR.test(String(mark.color ?? ""))) fail(`${at}.color must be a #rrggbb colour`);
    const points = numbers(mark.points, `${at}.points`);
    if (!points.length || points.length % 3) fail(`${at}.points must be x, y, z triples`);
    const count = points.length / 3;
    const out = { id, kind: mark.kind, part: mark.part ?? null, points, color: mark.color };
    if (mark.placement != null) out.placement = mark.placement;
    if (mark.view != null) out.view = String(mark.view);
    if (mark.opacity != null) {
      if (!(mark.opacity >= 0 && mark.opacity <= 1)) fail(`${at}.opacity must be between 0 and 1`);
      out.opacity = mark.opacity;
    }
    if (mark.kind === "stroke") {
      if (!(mark.width > 0)) fail(`${at}.width must be a positive number of pixels`);
      out.width = mark.width;
      if (mark.widths != null) {
        out.widths = numbers(mark.widths, `${at}.widths`);
        if (out.widths.length !== count) fail(`${at}.widths must have one value per point`);
      }
      out.dash = mark.dash ?? "solid";
      if (!DASHES.has(out.dash)) fail(`${at}.dash must be solid, dashed or dotted`);
      out.closed = Boolean(mark.closed);
      if (count < 2) fail(`${at}: a stroke has at least two points`);
    } else if (mark.kind === "area") {
      out.triangles = numbers(mark.triangles, `${at}.triangles`);
      if (!out.triangles.length || out.triangles.length % 3 || out.triangles.some(index => !Number.isInteger(index) || index < 0 || index >= count)) {
        fail(`${at}.triangles must index its points, three to a triangle`);
      }
      out.outline = mark.outline ?? count;
      if (!Number.isInteger(out.outline) || out.outline < 3 || out.outline > count) fail(`${at}.outline must count its outline's points`);
    } else {
      if (count !== 4) fail(`${at}: a text mark's points are its four corners`);
      out.text = String(mark.text ?? "");
      if (!(mark.fontPx > 0)) fail(`${at}.fontPx must be a positive number of pixels`);
      out.fontPx = mark.fontPx;
    }
    if (mark.group != null) out.group = String(mark.group);
    if (mark.touches != null) {
      if (!Array.isArray(mark.touches) || mark.touches.some(touch => typeof touch?.part !== "string")) fail(`${at}.touches must list { part } entries`);
      out.touches = mark.touches.map(touch => ({ part: touch.part }));
    }
    return out;
  });
  return { units, parts, marks };
}

const rounded = values => Array.from(values, value => Math.round(value * 1e4) / 1e4);
/**
 * An annotation as it is written: plain JSON, points to a ten-thousandth of a unit.
 * @param {{ units: string, marks: readonly AnnotationMark[], placements?: Map<string, ArrayLike<number>> | Record<string, ArrayLike<number>> }} annotation
 * @returns {Annotation}
 */
export function annotationDocument({ units, marks, placements = {} }) {
  const entries = placements instanceof Map ? [...placements] : Object.entries(placements);
  const used = new Set(marks.map(mark => mark.part).filter(part => part != null));
  const parts = Object.fromEntries(entries.filter(([id]) => used.has(id)).map(([id, placement]) => [id, { placement: rounded(placement) }]));
  return {
    units, parts,
    marks: marks.map(mark => {
      const out = { ...mark, points: rounded(mark.points) };
      if (mark.widths) out.widths = rounded(mark.widths);
      if (mark.triangles) out.triangles = Array.from(mark.triangles);
      return out;
    }),
  };
}

/** Whether an object and every parent of it is shown. */
export const annotationObjectShown = object => { for (let node = object; node; node = node.parent) if (!node.visible) return false; return true; };

/**
 * A part's own object under `root` (not an instanced draw of several), by occurrence id: what its
 * ink hangs on. The viewer's scene and a snapshot's both mark them `userData.partId`.
 * @returns {Map<string, import("three").Object3D>}
 */
export function annotationPartObjects(root) {
  const objects = new Map();
  root?.traverse?.(object => {
    if (object.isMesh && !object.isInstancedMesh && object.userData?.partId != null && !objects.has(String(object.userData.partId))) {
      objects.set(String(object.userData.partId), object);
    }
  });
  return objects;
}

// The pen's width along a stroke: three's screen-space line widens every segment by one uniform, so
// each segment carries its two ends' shares of it, and the feather the core line adds
// (`renderEdges.js`) is measured against the width there.
function taperedWidths(baseCompile) {
  return function inkTaperedLine(shader, renderer) {
    baseCompile?.call(this, shader, renderer);
    shader.vertexShader = `attribute float instanceWidthStart;\nattribute float instanceWidthEnd;\nvarying float vInkWidth;\n${shader.vertexShader}`
      .replace("void main() {", "void main() {\n\tfloat inkWidth = ( position.y < 0.5 ) ? instanceWidthStart : instanceWidthEnd;\n\tvInkWidth = inkWidth;")
      .replace(/offset \*= linewidth\b/, "offset *= linewidth * inkWidth");
    shader.fragmentShader = `varying float vInkWidth;\n${shader.fragmentShader}`
      .replace("float cadEdgeInkHalfWidth = linewidth * 0.5;", "float cadEdgeInkHalfWidth = linewidth * vInkWidth * 0.5;");
  };
}
let taperedCompile = null;

// A text mark's picture: its words as written, in the UI's face.
function textCanvas(mark) {
  const document = globalThis.document;
  if (!document?.createElement) return null;
  const scale = 2, font = `500 ${mark.fontPx * scale}px ui-sans-serif, system-ui, sans-serif`;
  const lines = String(mark.text).split("\n");
  const canvas = document.createElement("canvas");
  const context = canvas.getContext("2d");
  if (!context) return null;
  context.font = font;
  const width = Math.max(1, ...lines.map(line => context.measureText(line).width));
  canvas.width = Math.ceil(width) + 2;
  canvas.height = Math.ceil(lines.length * mark.fontPx * 1.25 * scale) + 2;
  context.font = font;
  context.fillStyle = mark.color;
  context.textBaseline = "top";
  lines.forEach((line, index) => context.fillText(line, 1, 1 + index * mark.fontPx * 1.25 * scale));
  return canvas;
}

/**
 * One mark's object: a stroke a screen-width line along its points, an area a flat mesh of its
 * triangles, a text mark its picture on a quad. Positioned by `placeAnnotationObject`.
 *
 * @param {{ THREE: typeof import("three"), Line2: any, LineGeometry: any, LineMaterial: any }} context
 * @param {AnnotationMark} mark
 * @param {{ radius: number, lineScale: number }} options  `radius`: the model's, which dashes are
 *   sized from. `lineScale`: device pixels per screen pixel of `width`.
 */
export function annotationMarkObject(context, mark, { radius, lineScale }) {
  const { THREE } = context;
  const positions = mark.points instanceof Float32Array ? mark.points : new Float32Array(mark.points);
  let object;
  if (mark.kind === "stroke") {
    object = createScreenSpaceLineStrip(context, positions, { color: mark.color, opacity: mark.opacity ?? 1,
      lineWidth: Math.max(1, mark.width * lineScale), renderOrder: ANNOTATION_RENDER_ORDER, depthTest: true, depthWrite: false });
    if (object && mark.widths?.length === positions.length / 3) {
      const segments = mark.widths.length - 1;
      object.geometry.setAttribute("instanceWidthStart", new THREE.InstancedBufferAttribute(new Float32Array(Array.from(mark.widths).slice(0, segments)), 1));
      object.geometry.setAttribute("instanceWidthEnd", new THREE.InstancedBufferAttribute(new Float32Array(Array.from(mark.widths).slice(1)), 1));
      // One callback for every tapered line, so they share a program.
      taperedCompile ??= taperedWidths(object.material.onBeforeCompile);
      object.material.onBeforeCompile = taperedCompile;
      object.material.needsUpdate = true;
    }
    if (object && mark.dash && mark.dash !== "solid") {
      object.computeLineDistances();
      object.material.dashed = true;
      object.material.dashSize = mark.dash === "dotted" ? radius * 0.0025 : radius * 0.02;
      object.material.gapSize = radius * 0.012;
      object.material.needsUpdate = true;
    }
  } else {
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    if (mark.kind === "area") {
      geometry.setIndex(Array.from(mark.triangles));
      const opacity = mark.opacity ?? 1;
      object = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({ color: mark.color, transparent: opacity < 1, opacity,
        side: THREE.DoubleSide, depthWrite: false, polygonOffset: true, polygonOffsetFactor: -1, polygonOffsetUnits: -4, toneMapped: false }));
    } else {
      geometry.setIndex([0, 1, 2, 0, 2, 3]);
      geometry.setAttribute("uv", new THREE.BufferAttribute(new Float32Array([0, 1, 1, 1, 1, 0, 0, 0]), 2));
      const canvas = textCanvas(mark);
      const material = new THREE.MeshBasicMaterial({ transparent: true, side: THREE.DoubleSide, depthWrite: false, toneMapped: false, visible: Boolean(canvas) });
      if (canvas) {
        material.map = new THREE.CanvasTexture(canvas);
        material.map.colorSpace = THREE.SRGBColorSpace;
      }
      object = new THREE.Mesh(geometry, material);
    }
    object.renderOrder = ANNOTATION_RENDER_ORDER;
  }
  if (object) {
    // Its world matrix is its part's, set by `placeAnnotationObject`: never recomputed from its parent.
    object.matrixAutoUpdate = false;
    object.matrixWorldAutoUpdate = false;
    object.frustumCulled = false;
  }
  return object;
}

/**
 * Puts a mark's object where its part is now: the part's frame as the scene has it, shown with it
 * and cut by `planes`; the part's placement when the annotation was made if the scene has no such part;
 * the model's own frame for a mark on no part.
 * @param {import("three").Object3D} object
 * @param {AnnotationMark} mark
 * @param {Map<string, import("three").Object3D>} parts  `annotationPartObjects`
 * @param {{ placements?: Record<string, { placement: ArrayLike<number> }>, planes?: import("three").Plane[], visible?: boolean }} [options]
 */
export function placeAnnotationObject(object, mark, parts, { placements = {}, planes = [], visible = true } = {}) {
  const part = mark.part != null ? parts.get(String(mark.part)) : null;
  const fallback = mark.part != null && !part ? placements[mark.part]?.placement : null;
  object.visible = visible && (mark.part == null || (part ? annotationObjectShown(part) : true));
  if (part) object.matrixWorld.copy(part.matrixWorld);
  else if (fallback?.length === 16) object.matrixWorld.fromArray(Array.from(fallback));
  else object.matrixWorld.identity();
  const material = object.material;
  if (material && (material.clippingPlanes?.length || 0) !== planes.length) material.needsUpdate = true;
  if (material) material.clippingPlanes = planes.length ? planes : null;
}

/** Frees a mark's object. */
export function disposeAnnotationObject(object) {
  object.removeFromParent();
  object.userData?.beforeDispose?.();
  object.geometry?.dispose?.();
  object.material?.map?.dispose?.();
  object.material?.dispose?.();
}

/**
 * A whole annotation drawn into a scene once, for a still: every mark's object under one group, placed
 * by its part under `partsRoot` as the scene has it when `place()` runs.
 *
 * @param {object} context  `THREE` and the screen-space line classes (`annotationMarkObject`).
 * @param {Annotation} annotation  `normalizeAnnotation`'s.
 * @param {{ radius: number, lineScale: number }} options
 */
export function createAnnotationLayer(context, annotation, options) {
  const { THREE } = context;
  const group = new THREE.Group();
  group.name = "annotation";
  const entries = annotation.marks.map(mark => ({ mark, object: annotationMarkObject(context, mark, options) })).filter(entry => entry.object);
  for (const { object } of entries) group.add(object);
  return {
    group,
    place(partsRoot, planes = []) {
      const parts = annotationPartObjects(partsRoot);
      partsRoot?.updateMatrixWorld?.(true);
      for (const { mark, object } of entries) placeAnnotationObject(object, mark, parts, { placements: annotation.parts, planes });
    },
    dispose() {
      for (const { object } of entries) disposeAnnotationObject(object);
      group.removeFromParent();
    },
  };
}
