import { useEffect, useRef } from "react";
import { Ruler } from "lucide-react";
import { projectWorldPointToClient } from "@text-to-cad/core/lib/viewer/measureRuler.js";
import { meshMeasurePick } from "@text-to-cad/core/lib/viewer/meshMeasure.js";
import { usePointerPick } from "../select/usePointerPick.js";
import { useMeasureOverlay } from "./useMeasureOverlay.js";

// Measure on a scene of triangles: points snapped to the triangles under the pointer
// (`meshMeasure.js`), lengths in the file's unit (the scene's `units`) and approximate, drawn and
// listed as exact measurements are (`useMeasureOverlay.js`, `measurementChips.jsx`). The session
// is the renderer's (`useMeasureSession`), since Quick Edit reads it before the shell is made.

/** The tool id a family's Measure takes on the strip. */
export const SCENE_MEASURE_TOOL = "measure";

/** Measure's strip icon: the ruler. */
export function MeasureIcon(props) {
  return <Ruler strokeWidth={2} {...props} />;
}

const pointArray = point => (Array.isArray(point) ? point : point?.toArray?.() ?? null);

/**
 * Measure's layer over the viewport: the measurements drawn, and while the tool is in hand
 * (`picking`) a pick per tap and a snap marker under the resting pointer. Draws nothing for a
 * scene that cannot be picked.
 *
 * @param {{ viewport: object, scene: object | null, measure: ReturnType<typeof import("./useMeasureSession.js").useMeasureSession>,
 *   picking: boolean, preview?: boolean }} props
 */
export function SceneMeasureOverlay({ viewport, scene, measure, picking, preview = false }) {
  const canvasRef = useRef(null);
  const hoverRef = useRef(null);
  const anchorRef = useRef(null);
  useEffect(() => { if (!picking) { hoverRef.current = null; anchorRef.current = null; } }, [picking]);
  useEffect(() => { if (!measure.state?.draft?.anchor) anchorRef.current = null; }, [measure.state]);
  const snap = (hit, pointer) => {
    const runtime = viewport.runtimeRef.current;
    if (!hit || !pointer || !runtime?.camera || !scene?.units) return null;
    const rect = { left: 0, top: 0, width: pointer.width, height: pointer.height };
    return meshMeasurePick({ ...hit, point: pointArray(hit.point) }, pointer, point => projectWorldPointToClient(point, runtime.camera, rect), scene.units);
  };
  usePointerPick({
    viewport, scene, enabled: picking && !preview,
    // Every pointer move snaps anew: the corner or side nearest it changes within one triangle.
    sameHit: () => false,
    onPick(hit, _modifiers, pointer) {
      const pick = snap(hit, pointer);
      if (!pick) return;
      // The first end holds the snap marker until the second is taken.
      if (!anchorRef.current) { anchorRef.current = pick; hoverRef.current = pick; } else anchorRef.current = null;
      measure.onPick(pick);
    },
    onHover(hit, pointer) {
      const pick = snap(hit, pointer);
      hoverRef.current = pick || anchorRef.current;
      measure.onHoverPoint(pick);
    }
  });
  useMeasureOverlay({
    measureCanvasRef: canvasRef, measureState: measure.state, activeMeasurementId: measure.activeId,
    selectedMeasurementIds: measure.selected, hoveredMeasurementId: measure.hovered, measureHoverRef: hoverRef,
    measureModeActive: picking, runtimeRef: viewport.runtimeRef, mountRef: viewport.mountRef, preview,
    viewerReadyTick: viewport.viewerReadyTick
  });
  return <canvas ref={canvasRef} className="absolute inset-0 z-10 h-full w-full touch-none" style={{ pointerEvents: "none" }} aria-hidden="true" data-scene-measure="" />;
}
