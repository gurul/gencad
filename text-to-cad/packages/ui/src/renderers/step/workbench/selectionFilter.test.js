import assert from 'node:assert/strict';
import test from 'node:test';
import { SELECT_GEOMETRY, connectedSelectionApplies, filterSelectionReferences, selectGeometryMode, toggleReferenceGroupSelection } from './selectionFilter.js';
const refs = [{id:'f1',selectorType:'face'}, {id:'f2',selectorType:'face'}, {id:'e1',selectorType:'edge'}];
test('a press picks the faces and edges the filter ticks, and no other topology', () => {
  assert.deepEqual(filterSelectionReferences(refs,['faces']).map(r=>r.id),['f1','f2']);
  assert.deepEqual(filterSelectionReferences(refs,['edges','position']).map(r=>r.id),['e1']);
  assert.deepEqual(filterSelectionReferences(refs,['parts']),[]);
  assert.deepEqual(filterSelectionReferences(refs,[]),[]);
  assert.equal(filterSelectionReferences(refs,['parts','faces','edges']),refs);
});
test('shift restores a saved face reference and toggles it off only when all members are selected', () => {
  assert.deepEqual(toggleReferenceGroupSelection(['f1'],['f2','f3'],true),['f1','f2','f3']);
  assert.deepEqual(toggleReferenceGroupSelection(['f1','f2'],['f2','f3'],true),['f1','f2','f3']);
  assert.deepEqual(toggleReferenceGroupSelection(['f1','f2','f3'],['f2','f3'],true),['f1']);
  assert.deepEqual(toggleReferenceGroupSelection(['f1'],['f2','f3']),['f2','f3']);
});
test('the geometry ticked is picked as one mode; Parts is an assembly\'s alone', () => {
  assert.deepEqual(SELECT_GEOMETRY.map(kind => kind.id), ['parts', 'faces', 'edges']);
  assert.deepEqual(SELECT_GEOMETRY.filter(kind => kind.assemblyOnly).map(kind => kind.id), ['parts']);
  const mode = filter => selectGeometryMode(filter);
  assert.deepEqual([mode(['parts', 'faces', 'edges']), mode(['parts', 'edges']), mode(['parts', 'annotation'])], ['all', 'all', 'parts']);
  assert.deepEqual([mode(['faces', 'edges']), mode(['faces']), mode(['edges', 'position']), mode(['position', 'measurement'])],
    ['topology', 'faces', 'edges', 'none']);
});
test('each connected option applies while its kind of topology is ticked', () => {
  const applies = filter => ['tangentFaces', 'edgeChain'].filter(id => connectedSelectionApplies(id, filter));
  assert.deepEqual(applies(['parts', 'faces', 'edges']), ['tangentFaces', 'edgeChain']);
  assert.deepEqual(applies(['faces']), ['tangentFaces']);
  assert.deepEqual(applies(['parts', 'edges']), ['edgeChain']);
  assert.deepEqual(applies(['parts', 'position']), []);
});
