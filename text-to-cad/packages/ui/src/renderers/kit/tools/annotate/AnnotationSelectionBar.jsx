import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { PaintBucket, Trash2 } from "lucide-react";
import { ToolbarButton } from "@text-to-cad/ui/primitives/toolbar-button";
import { cn } from "@text-to-cad/ui/utils";
import { FLOATING_CHROME_SURFACE_CLASS } from "../../../../lib/floatingSurface.js";
import { ANNOTATION_STROKE_WIDTHS, AnnotationStylePickers, annotationColors } from "../../../../annotation/toolbar.jsx";
import { fillMarkAt, interiorPoint, penWidth } from "../../../../annotation/geometry.js";
import { annotationsOnScreen, annotationWorldPoints, partObjects, projectAnnotations } from "./annotation3d.js";

// How far the bar keeps from the ink it is about, and from the viewport's edges, in px.
const GAP = 10;
const EDGE = 8;

// The setting a stroke was drawn at: the pen's ink is heavier than a shape's at the same one.
const strokeSetting = item => {
  const drawn = item.widths ? item.width / penWidth(1) : item.width;
  return ANNOTATION_STROKE_WIDTHS.reduce((best, option) => (Math.abs(option.value - drawn) < Math.abs(best.value - drawn) ? option : best)).value;
};
const closedShape = item => item.kind === "stroke" && item.closed && !item.widths;

/**
 * The ink Select has picked, its bar: a small floating toolbar just above it (below it where there
 * is no room above), following it as the camera and its parts move — the tool strip's surface, a
 * size smaller. Colour, and for strokes their weight, and for shapes their line style
 * (`AnnotationStylePickers`' dropdowns, each choice one step); Fill for a closed
 * shape (its interior, as it falls on the screen now, lying where the shape does, one step; again
 * to take it away); and Delete, which deletes everything Select has picked (`onDelete`), a
 * measurement too.
 *
 * @param {{ annotation: import("../../../../annotation/session.js").AnnotationSession, runtimeRef: { current: object | null },
 *   viewerReadyTick?: number, onDelete(): void, disabled?: boolean }} props
 */
export default function AnnotationSelectionBar({ annotation, colorScheme = "light", runtimeRef, viewerReadyTick = 0, onDelete, disabled = false }) {
  const picked = new Set(annotation.selected);
  const items = annotation.items.filter(item => picked.has(item.id));
  const itemsRef = useRef(items);
  itemsRef.current = items;
  const [box, setBox] = useState(/** @type {{ left: number, top: number, right: number, bottom: number, width: number, height: number } | null} */ (null));
  const key = items.map(item => item.id).join(",");
  // Each frame, where the picked ink falls on the screen, recomputed only when the camera or one of
  // its parts has moved since.
  useEffect(() => {
    if (!key) { setBox(null); return undefined; }
    let frame = 0, last = null, parts = null;
    const tick = () => {
      frame = globalThis.requestAnimationFrame(tick);
      const runtime = runtimeRef.current, canvas = runtime?.renderer?.domElement;
      if (!runtime?.camera || !canvas) return;
      if (!parts || [...parts.values()].some(object => !object.parent)) parts = partObjects(runtime);
      runtime.camera.updateMatrixWorld();
      const owners = itemsRef.current.map(item => (item.part != null ? parts.get(String(item.part)) : null)).filter(Boolean);
      const signature = [canvas.clientWidth, canvas.clientHeight, ...runtime.camera.matrixWorld.elements, ...runtime.camera.projectionMatrix.elements,
        ...owners.flatMap(object => { object.updateWorldMatrix(true, false); return [object.visible ? 1 : 0, ...object.matrixWorld.elements]; })];
      if (last && last.length === signature.length && last.every((value, index) => value === signature[index])) return;
      last = signature;
      const width = canvas.clientWidth, height = canvas.clientHeight;
      let left = Infinity, top = Infinity, right = -Infinity, bottom = -Infinity;
      for (const item of itemsRef.current) {
        for (const point of annotationWorldPoints(runtime, item, parts)) {
          const ndc = point.project(runtime.camera);
          if (ndc.z > 1) continue;
          const x = ((ndc.x + 1) / 2) * width, y = ((1 - ndc.y) / 2) * height;
          left = Math.min(left, x); right = Math.max(right, x); top = Math.min(top, y); bottom = Math.max(bottom, y);
        }
      }
      setBox(Number.isFinite(left) ? { left, top, right, bottom, width, height } : null);
    };
    tick();
    return () => globalThis.cancelAnimationFrame(frame);
  }, [key, runtimeRef, viewerReadyTick]);
  const bar = useRef(/** @type {HTMLDivElement | null} */ (null));
  const [size, setSize] = useState({ width: 0, height: 0 });
  useLayoutEffect(() => {
    const element = bar.current;
    if (element && (element.offsetWidth !== size.width || element.offsetHeight !== size.height)) setSize({ width: element.offsetWidth, height: element.offsetHeight });
  });
  if (!box || !items.length) return null;

  const strokes = items.filter(item => item.kind === "stroke");
  const shapes = strokes.filter(item => !item.widths);
  const closed = items.filter(closedShape);
  const filledGroups = new Set(annotation.items.filter(item => item.kind === "area" && item.group).map(item => item.group));
  const filled = closed.length > 0 && closed.every(item => item.group && filledGroups.has(item.group));
  const toggleFill = () => {
    if (filled) {
      const groups = new Set(closed.map(item => item.group));
      annotation.remove(annotation.items.filter(item => item.kind === "area" && groups.has(item.group)).map(item => item.id));
      return;
    }
    const runtime = runtimeRef.current, canvas = runtime?.renderer?.domElement;
    if (!runtime || !canvas) return;
    const view = { width: canvas.clientWidth, height: canvas.clientHeight };
    for (const shape of closed) {
      if (shape.group && filledGroups.has(shape.group)) continue;
      const [outline] = annotationsOnScreen(runtime, [shape], view);
      const seed = outline && interiorPoint(outline.points);
      const mark = seed && fillMarkAt(seed, [outline], shape.color);
      if (!mark) continue;
      annotation.fill(shape.id, projectAnnotations(runtime, [{ ...mark, placement: shape.placement ?? "surface", ...(shape.view ? { view: shape.view } : {}) }], view));
    }
  };

  const centre = (box.left + box.right) / 2;
  const left = Math.max(EDGE, Math.min(box.width - EDGE - size.width, centre - size.width / 2));
  const above = box.top - GAP - size.height;
  const top = above >= EDGE ? above : Math.min(box.bottom + GAP, box.height - EDGE - size.height);
  return <div ref={bar} role="toolbar" aria-label="Selected annotation"
    className={cn(FLOATING_CHROME_SURFACE_CLASS, "pointer-events-auto absolute z-20 rounded-md p-0.5", size.width ? null : "invisible")}
    style={{ left, top }} data-annotation-selection-bar="" onPointerDown={event => event.stopPropagation()}>
    <AnnotationStylePickers label="Selected annotation style" className="flex items-center gap-0.5" disabled={disabled} color={items[0].color} colors={annotationColors(colorScheme)}
      width={strokes.length ? strokeSetting(strokes[0]) : null} dash={shapes.length ? shapes[0].dash ?? "solid" : null}
      onColor={color => annotation.restyle({ color })} onWidth={width => annotation.restyle({ width })} onDash={dash => annotation.restyle({ dash })}>
      {closed.length ? <ToolbarButton tooltip={false} label="Fill" disabled={disabled} active={filled} aria-pressed={filled} onClick={toggleFill}>
        <PaintBucket className="size-3" strokeWidth={2} aria-hidden="true" />
      </ToolbarButton> : null}
      <span role="separator" aria-orientation="vertical" className="mx-0.5 h-4 w-px bg-border" />
      <ToolbarButton tooltip={false} label="Delete" disabled={disabled} onClick={onDelete}>
        <Trash2 className="size-3" strokeWidth={2} aria-hidden="true" />
      </ToolbarButton>
    </AnnotationStylePickers>
  </div>;
}
