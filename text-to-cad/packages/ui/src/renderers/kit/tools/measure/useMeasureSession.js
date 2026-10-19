import { useCallback, useEffect, useRef, useState } from "react";
import {
  applyMeasureRulerDelete,
  applyMeasureRulerHover,
  applyMeasureRulerPick,
  cancelMeasureRulerDraft,
  measureRulerStateForChange
} from "./measureRulerState.js";

const NO_MEASUREMENTS = Object.freeze([]);

/**
 * The Measure tool's session, in any 3D file: the measurement being drawn and the ones taken
 * (between two points, each where the pick snapped: exact vertices, edges and faces where the
 * renderer has them, else a mesh's triangles), and which is highlighted. The viewport feeds it picks and hovers; Quick
 * Edit's chips read the measurements (`measurementChips.jsx`).
 *
 * Measurements outlive the tool (they are cleared on purpose, or with the file's geometry);
 * a draft does not — putting the tool down drops it. The highlighted row follows a new measurement, and otherwise stays where the person
 * put it until that row is gone; only a change to the LIST moves it, so a draft's hover ticks
 * never fight a row click. Under Select, measurements are hovered and picked as anything is
 * (`hovered`/`hover`, `selected`/`select`), haloed in the view, and Delete deletes them
 * (`removeSelected`).
 *
 * @param {{ fileKey: string, revision: string, picking: boolean }} options  `picking`: the tool
 *   is in hand and can pick now.
 */
export function useMeasureSession({ fileKey, revision, picking }) {
  const [state, setState] = useState(null);
  const [activeId, setActiveId] = useState("");
  const onPick = useCallback((pick) => {
    setState((current) => applyMeasureRulerPick(current, pick));
  }, []);
  const onHoverPoint = useCallback((hover) => {
    setState((current) => applyMeasureRulerHover(current, hover));
  }, []);
  const onDelete = useCallback((id) => setState((current) => applyMeasureRulerDelete(current, id)), []);
  const cancelDraft = useCallback(() => setState((current) => cancelMeasureRulerDraft(current)), []);
  const clear = useCallback(() => { setState(null); setActiveId(""); }, []);
  const measurements = state?.measurements || NO_MEASUREMENTS;
  useEffect(() => {
    setState((current) => measureRulerStateForChange(current, { entryChanged: true }));
  }, [fileKey, revision]);
  useEffect(() => {
    if (!picking) setState((current) => measureRulerStateForChange(current, { toolActive: false }));
  }, [picking]);
  const countRef = useRef(0);
  useEffect(() => {
    const count = measurements.length;
    const grew = count > countRef.current;
    countRef.current = count;
    const newest = count ? measurements[count - 1].id : "";
    setActiveId((current) => (!grew && current && measurements.some((item) => item.id === current) ? current : newest));
  }, [measurements]);
  // What Select has picked: the measurements Delete deletes. A measurement gone takes its pick with it.
  const [selected, setSelected] = useState(NO_MEASUREMENTS);
  useEffect(() => {
    setSelected((current) => (current.every((id) => measurements.some((item) => item.id === id)) ? current
      : current.filter((id) => measurements.some((item) => item.id === id))));
  }, [measurements]);
  const selectedRef = useRef(selected);
  selectedRef.current = selected;
  const removeSelected = useCallback(() => {
    const ids = selectedRef.current;
    if (!ids.length) return false;
    setState((current) => ids.reduce((next, id) => applyMeasureRulerDelete(next, id), current));
    setSelected(NO_MEASUREMENTS);
    return true;
  }, []);
  // What the pointer rests on under Select: lit as a part is, until it moves off or the measurement goes.
  const [hovered, setHovered] = useState("");
  useEffect(() => {
    setHovered((current) => (current && !measurements.some((item) => item.id === current) ? "" : current));
  }, [measurements]);
  return { state, measurements, activeId, setActiveId, drafting: Boolean(state?.draft?.anchor),
    onPick, onHoverPoint, onDelete, cancelDraft, clear, selected, select: setSelected, removeSelected, hovered, hover: setHovered };
}
