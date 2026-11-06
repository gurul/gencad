import { useMemo } from "react";
import { measureLabelText, measureSeriesColor, measurementMark } from "@text-to-cad/core/lib/viewer/measureDimension.js";
import MeasurementCard from "./MeasurementCard.jsx";

/**
 * Measure's results as Quick Edit has them (`useRendererShell`'s `measurements`), in any 3D file:
 * each its colour's ruler and its reading — a mesh's said to be approximate — its X deleting it,
 * resting on it lighting it, its card the full reading; and the marks a note's views are drawn
 * with (`measureDimension.js`'s `measurementMark`, as the viewer draws them). Chips never copy
 * references or write files; Copy Prompt, Queue and Send carry the marks in the snapshot packet.
 * None while nothing is measured.
 *
 * @param {ReturnType<typeof import("./useMeasureSession.js").useMeasureSession>} measure
 */
export function useQuickEditMeasurements(measure) {
  const items = measure.measurements;
  const { onDelete, hover, clear } = measure;
  const chips = useMemo(() => items.map((item, index) => {
    const reading = measureLabelText(item.measurement);
    return { key: `measure-${item.id}`, label: `Measurement ${index + 1}: ${reading}${item.measurement?.approximate ? " (approximate)" : ""}`, text: reading,
      glyph: "ruler", glyphColor: measureSeriesColor(item.colorIndex),
      card: <MeasurementCard item={item} />,
      onRemove: () => onDelete(item.id), onHover: on => hover(on ? item.id : "") };
  }), [items, onDelete, hover]);
  return useMemo(() => (items.length ? { chips, clear, marks: () => items.map(measurementMark).filter(Boolean) } : null), [items, chips, clear]);
}
