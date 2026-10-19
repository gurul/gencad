import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { useAnnotationSession } from './session.js';
import { useViewerHistory } from '../renderers/kit/shell/useViewerHistory.js';

afterEach(cleanup);
const CAD = { tool: 'freedraw', color: '#ff2d55' };
const stroke = (id: string, extra = {}) => ({ id, kind: 'stroke', part: null, points: new Float32Array(6), color: '#ff2d55', width: 2, dash: 'solid', ...extra });
const view = (x: number) => ({ camera: { position: [x, -100, 0], target: [0, 0, 0], up: [0, 0, 1], orthographicHalfHeight: 50 }, width: 1600, height: 1200 });

it('holds the ink, each add, erase or restyle one step to undo and redo; clear is one more, discard leaves nothing to undo', () => {
  const session = renderHook(() => useAnnotationSession(true, CAD));
  const current = () => session.result.current;
  expect(current()).toMatchObject({ ready: true, tool: 'freedraw', color: '#ff2d55', strokeWidth: 2, strokeStyle: 'solid', placement: 'surface', hasContent: false });
  act(() => current().add([stroke('a'), stroke('b')]));
  act(() => current().remove(['a']));
  act(() => current().select(['b']));
  act(() => current().restyle({ color: '#00e5ff' }));
  expect(current().items.map(item => [item.id, item.color])).toEqual([['b', '#00e5ff']]);
  act(() => current().undo());
  act(() => current().undo());
  expect(current().items.map(item => item.id)).toEqual(['a', 'b']);
  act(() => current().redo());
  expect(current().items.map(item => item.id)).toEqual(['b']);
  act(() => current().clear());
  expect(current()).toMatchObject({ hasContent: false, canUndo: true });
  act(() => current().undo());
  expect(current().hasAnnotation).toBe(true);
  act(() => current().discard());
  expect(current()).toMatchObject({ hasContent: false, canUndo: false, canRedo: false });
});

it("Annotate's colour, weight, line style and placement are what is drawn next; the selection's restyle is one step, the pen's weight its own", () => {
  const session = renderHook(() => useAnnotationSession(true, CAD));
  const current = () => session.result.current;
  act(() => current().add([stroke('a'), stroke('b'), stroke('p', { widths: [1, 1] })]));
  act(() => current().select(['a', 'p']));
  act(() => { current().selectColor('#39ff14'); current().selectStrokeWidth(4); current().selectStrokeStyle('dashed'); current().selectPlacement('space'); });
  expect(current()).toMatchObject({ color: '#39ff14', strokeWidth: 4, strokeStyle: 'dashed', placement: 'space', canUndo: true });
  expect(current().items.map(item => item.color)).toEqual(['#ff2d55', '#ff2d55', '#ff2d55']);
  act(() => current().restyle({ color: '#ffffff', width: 4, dash: 'dotted' }));
  expect(current().items.map(item => [item.id, item.color, item.width, item.dash])).toEqual([
    ['a', '#ffffff', 4, 'dotted'], ['b', '#ff2d55', 2, 'solid'], ['p', '#ffffff', 6, 'solid']]);
  act(() => current().undo());
  expect(current().items.map(item => item.color)).toEqual(['#ff2d55', '#ff2d55', '#ff2d55']);
});

it("a fill joins its shape's group in its colour, one step; an undo takes the pick of ink it removes", () => {
  const session = renderHook(() => useAnnotationSession(true, CAD));
  const current = () => session.result.current;
  act(() => current().add([stroke('r', { closed: true, color: '#00e5ff' })]));
  act(() => current().fill('r', [{ id: 'f', kind: 'area', part: null, points: new Float32Array(9), color: '#ff2d55' } as any]));
  const [shape, fill] = current().items;
  expect(fill).toMatchObject({ id: 'f', color: '#00e5ff', group: shape.group });
  expect(shape.group).toBeTruthy();
  act(() => current().select(['r', 'f']));
  act(() => current().undo());
  expect(current().items.map(item => item.id)).toEqual(['r']);
  expect(current().selected).toEqual(['r']);
});

it("shares the file view's history: Undo walks the steps of every tool in the order they were taken", () => {
  const shared = renderHook(() => {
    const history = useViewerHistory();
    return { history, session: useAnnotationSession(true, CAD, history) };
  });
  const current = () => shared.result.current;
  const other: string[] = [];
  act(() => current().session.add([stroke('a')]));
  act(() => current().history.record({ source: 'measure', undo: () => other.push('undo'), redo: () => other.push('redo') }));
  act(() => current().session.add([stroke('b')]));
  act(() => { current().history.undo(); });
  act(() => { current().history.undo(); });
  expect([current().session.items.map(item => item.id), other]).toEqual([['a'], ['undo']]);
  act(() => { current().history.redo(); });
  expect(other).toEqual(['undo', 'redo']);
  // An annotation discarded takes only its own steps out.
  act(() => current().session.discard());
  expect(current().history).toMatchObject({ canUndo: true, canRedo: false });
  act(() => { current().history.undo(); });
  expect(other).toEqual(['undo', 'redo', 'undo']);
  expect(current().history.canUndo).toBe(false);
});

it('names the view ink goes down in: one drawn in before that is the same, or a new one; discard forgets them', () => {
  const session = renderHook(() => useAnnotationSession(true, CAD));
  const current = () => session.result.current;
  let labels: (string | undefined)[] = [];
  act(() => { labels = [current().noteView(view(0)), current().noteView(view(1)), current().noteView(view(100)), current().noteView(null)]; });
  expect(labels).toEqual(['view 1', 'view 1', 'view 2', undefined]);
  expect(current().views.map(entry => entry.label)).toEqual(['view 1', 'view 2']);
  act(() => current().discard());
  expect(current().views).toEqual([]);
});

it("put down, Annotate keeps the tool in hand, the ink, Select's pick of it, the colour, the weight, the line style and the placement", () => {
  const session = renderHook(({ active }) => useAnnotationSession(active, CAD), { initialProps: { active: true } });
  const current = () => session.result.current;
  act(() => { current().add([stroke('a')]); current().selectTool('eraser'); current().select(['a']); });
  act(() => { current().selectColor('#ffffff'); current().selectStrokeWidth(4); current().selectStrokeStyle('dotted'); current().selectPlacement('space'); });
  session.rerender({ active: false });
  expect(current()).toMatchObject({ tool: 'eraser', selected: ['a'], color: '#ffffff', strokeWidth: 4, strokeStyle: 'dotted', placement: 'space', hasAnnotation: true });
});
