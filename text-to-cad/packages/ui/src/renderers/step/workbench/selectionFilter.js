/**
 * The kinds of the model's geometry Select picks, each a checkbox of its selection filter
 * (`kit/tools/select/selectFilter.js`), each on its own. `assemblyOnly`: a single part is one
 * thing, so picking parts in it would pick nothing but the whole: a part file's filter offers no
 * Parts, and picks the whole part where a press reaches no face or edge.
 */
export const SELECT_GEOMETRY = Object.freeze([
  { id: 'parts', label: 'Parts', assemblyOnly: true },
  { id: 'faces', label: 'Faces' },
  { id: 'edges', label: 'Edges' },
]);

/**
 * How the geometry a filter ticks is picked, as one mode: "all" — Parts with Faces or Edges — a
 * press takes the face or edge it lands on where the part's topology can be picked, the part
 * elsewhere; "parts", the part alone; "topology" — Faces and Edges — "faces" and "edges" that
 * topology alone, loading a part's when a press first reaches it; "none", no geometry.
 */
export function selectGeometryMode(filter) {
  const parts = filter.includes('parts'), faces = filter.includes('faces'), edges = filter.includes('edges');
  if (parts) return faces || edges ? 'all' : 'parts';
  if (faces && edges) return 'topology';
  return faces ? 'faces' : edges ? 'edges' : 'none';
}

/**
 * How a face or edge pick grows, independent of the filter and of each other: Group faces takes
 * the smoothly joined faces with a picked face, Group edges the connected edges with a picked
 * edge. Each applies while its kind of topology is ticked, and has no effect otherwise.
 */
export const CONNECTED_SELECTION = [
  { id: 'edgeChain', label: 'Group edges', kind: 'edges' },
  { id: 'tangentFaces', label: 'Group faces', kind: 'faces' },
];
export const NO_CONNECTED_SELECTION = Object.freeze({ edgeChain: false, tangentFaces: false });

/** Whether a connected-selection option does anything under `filter` (its kind ticked). */
export function connectedSelectionApplies(id, filter) {
  const kind = CONNECTED_SELECTION.find(option => option.id === id)?.kind;
  return Boolean(kind) && filter.includes(kind);
}

/** What a viewport press can pick of `references` under `filter`: the faces and edges it ticks. */
export function filterSelectionReferences(references, filter) {
  const faces = filter.includes('faces'), edges = filter.includes('edges');
  if (faces && edges) return references;
  return references.filter(r => (faces && r.selectorType === 'face') || (edges && r.selectorType === 'edge'));
}

export function toggleReferenceGroupSelection(current, referenceIds, additive = false) {
  if (!additive) return [...referenceIds];
  const next = new Set(current);
  const remove = referenceIds.every(id => next.has(id));
  for (const id of referenceIds) {
    if (remove) next.delete(id);
    else next.add(id);
  }
  return [...next];
}

export function connectedReferenceIds(graph, seed) {
  if (!graph.has(seed)) return [];
  const selected = new Set([seed]);
  const pending = [seed];
  while (pending.length) {
    for (const id of graph.get(pending.pop()) || []) {
      if (selected.has(id)) continue;
      selected.add(id);
      pending.push(id);
    }
  }
  return [...selected];
}
