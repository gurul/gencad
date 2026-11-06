import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { sameView } from './views.js';
import { useViewerHistory } from '../renderers/kit/shell/useViewerHistory.js';
import { penWidth } from './geometry.js';

/**
 * The annotation: one annotation, its ink in the model (`renderers/kit/tools/annotate/annotation3d.js`'s items), what
 * Annotate's tools put down next (`tool`, `color`, `strokeWidth`, `strokeStyle`, `placement`) and its history. It
 * outlives Annotate being put down — the ink stays in the model, and the next time Annotate is taken up it
 * draws on it — and goes when the person clears it or the model it was drawn on changes (`discard`).
 * Each change to the ink is a step in the file view's one history (`useViewerHistory`), which
 * Undo and Redo walk whatever tool took the step.
 *
 * @typedef {object} AnnotationSession
 * @property {boolean} ready  Always: the toolbar's tools are the session's own.
 * @property {import('./toolbar.jsx').AnnotationTool} tool
 * @property {string} color
 * @property {number} strokeWidth
 * @property {import('./toolbar.jsx').AnnotationStrokeStyle} strokeStyle
 * @property {import('./toolbar.jsx').AnnotationPlacement} placement  Where what is drawn next lies: on
 *   the model, or in space on a plane facing the view.
 * @property {readonly import('../renderers/kit/tools/annotate/annotation3d.js').AnnotationItem[]} items
 * @property {readonly string[]} selected  The ink the viewer's Select has picked: what the selection's bar
 *   (`restyle`, `fill`) and Delete act on. Annotate's tools never pick ink.
 * @property {boolean} canUndo
 * @property {boolean} canRedo
 * @property {boolean} hasContent  There is ink.
 * @property {boolean} hasAnnotation  The same: there is an annotation.
 * @property {(tool: import('./toolbar.jsx').AnnotationTool) => void} selectTool
 * @property {(color: string) => void} selectColor  What is drawn next.
 * @property {(width: number) => void} selectStrokeWidth  What is drawn next.
 * @property {(style: import('./toolbar.jsx').AnnotationStrokeStyle) => void} selectStrokeStyle  What is drawn next.
 * @property {(placement: import('./toolbar.jsx').AnnotationPlacement) => void} selectPlacement  What is drawn next: ink already down stays where it lies.
 * @property {(style: { color?: string, width?: number, dash?: import('./toolbar.jsx').AnnotationStrokeStyle }) => void} restyle
 *   The ink selected, as one step: its colour, a stroke's weight (a shape's at that width, the pen's
 *   heavier, as each draws), a shape's line style.
 * @property {(shape: string, areas: readonly import('../renderers/kit/tools/annotate/annotation3d.js').AnnotationItem[]) => void} fill
 *   A closed shape filled, as one step: the fill joins the shape's group, picked and deleted with it.
 * @property {(items: readonly import('../renderers/kit/tools/annotate/annotation3d.js').AnnotationItem[]) => void} add  Ink put down: one step.
 * @property {(ids: readonly string[]) => void} remove  Ink erased or deleted: one step.
 * @property {(ids: readonly string[]) => void} select
 * @property {() => void} undo
 * @property {() => void} redo
 * @property {() => void} clear  Every piece of ink, as one step to undo.
 * @property {() => void} forget  The same as `clear`.
 * @property {() => void} discard  Every piece of ink and the history with it: nothing to undo.
 * @property {readonly import('./views.js').LabelledView[]} views  The views ink was drawn in, in order
 *   ("view 1", "view 2"…): a mark names its own (`view`).
 * @property {(view: import('./views.js').PromptView | null) => string | undefined} noteView  The label of
 *   the view ink is being put down in: the one drawn in before that is the same (`sameView`), or a new one.
 */

const DEFAULTS = Object.freeze({ tool: 'freedraw', color: '#ff2d55', strokeWidth: 2, strokeStyle: 'solid', placement: 'surface' });
const NO_ANNOTATIONS = Object.freeze([]);

/**
 * @param {boolean} [active]  Annotate is the tool. Put down, it goes back to its first tool (the pen);
 *   the ink, its selection, the colour, the weight, the line style and the placement stay.
 * @param {{ tool?: string, color?: string, strokeWidth?: number, strokeStyle?: import('./toolbar.jsx').AnnotationStrokeStyle,
 *   placement?: import('./toolbar.jsx').AnnotationPlacement }} [initial]
 * @param {import('../renderers/kit/shell/useViewerHistory.js').ViewerHistory | null} [history]  The file
 *   view's; without one the session keeps its own.
 * @returns {AnnotationSession}
 */
export function useAnnotationSession(active = true, initial = {}, history = null) {
  const start = useMemo(() => ({ ...DEFAULTS, ...Object.fromEntries(Object.entries(initial).filter(([, value]) => value != null)) }),
    [initial.tool, initial.color, initial.strokeWidth, initial.strokeStyle, initial.placement]);
  const [tool, setTool] = useState(start.tool);
  const [color, setColor] = useState(start.color);
  const [strokeWidth, setStrokeWidth] = useState(start.strokeWidth);
  const [strokeStyle, setStrokeStyle] = useState(start.strokeStyle);
  const [placement, setPlacement] = useState(start.placement);
  const own = useViewerHistory();
  const log = history ?? own;
  const logRef = useRef(log);
  logRef.current = log;
  // The ink; each step records the ink before and after it, so Undo and Redo put either back.
  const [items, setItems] = useState(/** @type {readonly import('../renderers/kit/tools/annotate/annotation3d.js').AnnotationItem[]} */ (NO_ANNOTATIONS));
  const itemsRef = useRef(items);
  const [selected, setSelected] = useState(/** @type {string[]} */ ([]));
  // The views ink was drawn in. Not a step to undo: a label a mark names stays, whatever is undone.
  const viewsRef = useRef(/** @type {import('./views.js').LabelledView[]} */ ([]));
  const [views, setViews] = useState(viewsRef.current);
  const noteView = useCallback(view => {
    if (!view) return undefined;
    const known = viewsRef.current.findLast(drawn => sameView(drawn, view));
    if (known) return known.label;
    const label = `view ${viewsRef.current.length + 1}`;
    viewsRef.current = [...viewsRef.current, { ...view, label }];
    setViews(viewsRef.current);
    return label;
  }, []);
  const put = useCallback(next => { itemsRef.current = next; setItems(next); }, []);
  const step = useCallback(change => {
    const before = itemsRef.current;
    const after = change(before);
    if (after === before) return;
    put(after);
    logRef.current.record({ source: 'annotation', undo: () => put(before), redo: () => put(after) });
  }, [put]);
  // Ink an undo took away takes its pick with it.
  useEffect(() => {
    setSelected(current => (current.every(id => items.some(item => item.id === id)) ? current
      : current.filter(id => items.some(item => item.id === id))));
  }, [items]);
  const add = useCallback(items => { if (items.length) step(current => [...current, ...items]); }, [step]);
  const remove = useCallback(ids => {
    const gone = new Set(ids);
    if (!gone.size) return;
    step(current => (current.some(item => gone.has(item.id)) ? current.filter(item => !gone.has(item.id)) : current));
    setSelected(current => current.filter(id => !gone.has(id)));
  }, [step]);
  const selectedRef = useRef(selected);
  selectedRef.current = selected;
  const actions = useMemo(() => ({
    selectTool: next => setTool(next),
    selectColor: next => setColor(next),
    selectStrokeWidth: next => setStrokeWidth(next),
    selectStrokeStyle: next => setStrokeStyle(next),
    // Not a style: ink already down, selected or not, stays where it lies.
    selectPlacement: next => setPlacement(next),
    restyle: ({ color: nextColor, width, dash }) => {
      const ids = new Set(selectedRef.current);
      if (!ids.size) return;
      step(current => {
        let changed = false;
        const next = current.map(item => {
          if (!ids.has(item.id)) return item;
          const styled = { ...item };
          if (nextColor != null && item.color !== nextColor) styled.color = nextColor;
          if (width != null && item.kind === 'stroke') {
            // The pen's own weight is heavier than a shape's at the same setting (`inkGeometry.js`).
            const drawn = item.widths ? penWidth(width) : width;
            if (item.width !== drawn) styled.width = drawn;
          }
          // The pen's freehand ink stays solid.
          if (dash != null && item.kind === 'stroke' && !item.widths && item.dash !== dash) styled.dash = dash;
          if (Object.keys(styled).some(key => styled[key] !== item[key])) { changed = true; return styled; }
          return item;
        });
        return changed ? next : current;
      });
    },
    fill: (shape, areas) => {
      if (!areas.length) return;
      step(current => {
        const target = current.find(item => item.id === shape);
        if (!target) return current;
        const group = target.group ?? `group-${shape}`;
        return [...current.map(item => (item.id === shape && !item.group ? { ...item, group } : item)),
          ...areas.map(area => ({ ...area, group, color: target.color }))];
      });
      // A picked shape's fill is picked with it, as its group is.
      setSelected(current => (current.includes(shape) ? [...current, ...areas.map(area => area.id)] : current));
    },
    select: ids => setSelected([...ids]),
    undo: () => { logRef.current.undo(); },
    redo: () => { logRef.current.redo(); },
    clear: () => { step(current => (current.length ? NO_ANNOTATIONS : current)); setSelected([]); },
    discard: () => {
      put(NO_ANNOTATIONS);
      logRef.current.forget('annotation');
      setSelected([]);
      viewsRef.current = [];
      setViews([]);
    },
  }), [step, put]);
  const hasContent = items.length > 0;
  return { ready: true, tool, color, strokeWidth, strokeStyle, placement, items, selected, views,
    canUndo: log.canUndo, canRedo: log.canRedo, hasContent, hasAnnotation: hasContent,
    add, remove, noteView, forget: actions.clear, ...actions };
}
