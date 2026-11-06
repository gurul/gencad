import { useCallback, useMemo, useRef } from 'react';
import { buildPositionSection } from './MotionControlsSection.js';
import { useStepReferenceChips } from './StepReferenceSection.js';
import ModelingTree from './ModelingTree.jsx';
import ToolPanel from '../../../kit/tools/ToolPanel.jsx';
import { stepGeometryMeasurements } from '../../workbench/stepGeometryMeasurements.js';
const EMPTY = [];

/**
 * `fn` behind one identity for the life of the panels, calling whatever `fn` is now: the tree's
 * rows are memoized, so a host callback rebuilt on every render must not re-render them. Absent
 * stays absent (a row reads whether an action is offered from whether its callback exists).
 */
function useLatestCallback(fn) {
  const latest = useRef(fn);
  latest.current = fn;
  const stable = useCallback((...args) => latest.current?.(...args), []);
  return typeof fn === 'function' ? stable : fn;
}

/** An object of callbacks (`partMenuActions`) the same way: one object while its names stay the same. */
function useLatestActions(actions) {
  const latest = useRef(actions);
  latest.current = actions;
  const names = actions ? Object.keys(actions).filter(name => typeof actions[name] === 'function').sort().join('\n') : null;
  return useMemo(() => names === null ? actions : Object.fromEntries(names.split('\n').filter(Boolean)
    .map(name => [name, (...args) => latest.current?.[name]?.(...args)])), [names]);
}

/**
 * What is selected, as Quick Edit's chips (`useStepReferenceChips`): each face, edge or run of them
 * named after its part as the tree names that part, with its key measurements for its card — a
 * part's or subassembly's size from the boxes of the parts it is made of. `onRemove(ids)` and
 * `onHover(target)` are the host's: what a chip's X drops and what resting on it lights.
 */
export function useStepSelectionChips({ stepTreeRoot, selectedMeshData = null, geometryInspection = null, references = EMPTY,
  onRemove = null, onHover = null, copyText = null }) {
  const modelParts = geometryInspection?.parts || EMPTY;
  const partsSize = useCallback(ids => stepGeometryMeasurements({ partIds: ids }, EMPTY, modelParts).size, [modelParts]);
  const partNames = useMemo(() => {
    const names = new Map();
    const visit = node => { if (!node) return; if (node.id) names.set(String(node.id), String(node.displayName || node.name || '').trim()); (node.children || EMPTY).forEach(visit); };
    visit(stepTreeRoot);
    return names;
  }, [stepTreeRoot]);
  const partName = useCallback(id => partNames.get(String(id || '')) || '', [partNames]);
  const remove = useLatestCallback(onRemove), hover = useLatestCallback(onHover);
  return useStepReferenceChips({ references, meshData: selectedMeshData, partsSize, partName, onRemove: remove, onHover: hover, copyText });
}

/**
 * A STEP's sections in the file sidebar, top to bottom, whatever the tool: an assembly's
 * **Features** (the filter and the model tree; a part file, whose tree would be its one row, has
 * none, and Select's filter is the chevron after its button on the strip), then **Position**, its
 * joints, where it has any. What is picked is Quick Edit's to show, as chips
 * (`useStepSelectionChips`). Null where there is neither: no sidebar. The kept effects' panels are
 * the tool stack's (`kit/tools/model-effects/ModelTools.jsx`); the sidebar itself is the shell's
 * (`kit/shell/RendererShell.jsx`).
 *
 * `selectActive`: Features is on screen, which is when a pick is scrolled to. `selectMode` is the
 * Select tool's geometry, which the tree's disclosure follows. Setting a Position control puts any
 * other motion at rest (the motion hook's `claimPosition`); pressing one sets nothing.
 */
export function useStepPanels({
  selectActive, selectedEntry, viewerLoading,
  geometryInspection = null, stepTreeRoot, isAssemblyView = false,
  selectedPartIds = EMPTY, selectedReferences = EMPTY,
  hiddenPartIds = EMPTY, focusedNodeIds = EMPTY, selectableNodeIds = null,
  expandedTreeNodeIds = EMPTY, onToggleTreeNode,
  activeTreeNodeScrollKey = '', onSelectTreeNode, onClearSelection,
  onFocusTreeNode, onUnfocusTreeNode, onExitAllIsolate, onTogglePartVisibility,
  onHoverTreeNode, showAllHiddenParts,
  // The menu a tree row carries: a node's part menu descriptor, and the actions behind it.
  menuForNode = null, partMenuActions = null,
  treeSelectionDisabled = false, selectMode = 'all', loadingGeometry = false,
  positionRuntime = null, positionChanged = false,
  // The viewport's hover (`workbench/hoverStore.js`): a large tree under Faces or Edges asks for the
  // topology of the part the pointer rests on.
  hoverStore = null,
}) {
  // What every tree row is handed, the same object until something in it changes: the host's
  // actions behind stable identities, its menus and state as they are.
  const toggleTreeNode = useLatestCallback(onToggleTreeNode), selectTreeNode = useLatestCallback(onSelectTreeNode);
  const focusTreeNode = useLatestCallback(onFocusTreeNode), unfocusTreeNode = useLatestCallback(onUnfocusTreeNode);
  const exitAllIsolate = useLatestCallback(onExitAllIsolate), togglePartVisibility = useLatestCallback(onTogglePartVisibility);
  const showAll = useLatestCallback(showAllHiddenParts);
  const hoverTreeNode = useLatestCallback(onHoverTreeNode);
  // A row's menu is built when it opens, from the host's descriptor as it is then.
  const nodeMenu = useLatestCallback(menuForNode);
  const menuActions = useLatestActions(partMenuActions);
  const partControls = useMemo(() => ({ isAssemblyView, hiddenPartIds, focusedNodeIds, selectableNodeIds, expandedTreeNodeIds,
    onToggleTreeNode: toggleTreeNode, onSelectTreeNode: selectTreeNode, onFocusTreeNode: focusTreeNode, onUnfocusTreeNode: unfocusTreeNode,
    onExitAllIsolate: exitAllIsolate, onTogglePartVisibility: togglePartVisibility, showAllHiddenParts: showAll,
    onHoverTreeNode: hoverTreeNode, menuForNode: nodeMenu, partMenuActions: menuActions }), [isAssemblyView,
    hiddenPartIds, focusedNodeIds, selectableNodeIds, expandedTreeNodeIds, toggleTreeNode, selectTreeNode, focusTreeNode, unfocusTreeNode,
    exitAllIsolate, togglePartVisibility, showAll, hoverTreeNode, nodeMenu, menuActions]);
  const loadTopology = useLatestCallback(geometryInspection?.onLoadTopology);
  const clearSelection = useLatestCallback(onClearSelection);
  if (!selectedEntry) return null;
  const position = buildPositionSection({ poseRuntime: positionRuntime });
  if (!isAssemblyView && !position) return null;
  const disabled = treeSelectionDisabled || viewerLoading;
  return <>
    {isAssemblyView ? <ModelingTree key={`${selectedEntry.file}:${geometryInspection?.revision}`}
      stepRoot={stepTreeRoot} active={selectActive} mode={selectMode} loading={loadingGeometry} disabled={disabled}
      selectedReferences={selectedReferences} selectedPartIds={selectedPartIds} activeTreeNodeScrollKey={activeTreeNodeScrollKey}
      onLoadTopology={loadTopology} onClearSelection={clearSelection}
      partControls={partControls} hoverStore={hoverStore}
    /> : null}
    {/* Headed "Position"; its Pose row's Default puts the joints back. Another tool puts Position
        down, and the values stay. */}
    {position ? <ToolPanel id="position" title={position.title} label="Position controls" fit="details" changed={positionChanged}>
      {position.content}
    </ToolPanel> : null}
  </>;
}
