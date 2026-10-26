import { STEP_MODEL_ROOT_ID } from "@text-to-cad/core/lib/step/stepTree.js";
import { buildSelectionCopyPayload, buildWholeStepEntryCopyReference } from "../workbench/referenceSelection.js";
import {
  copyPayloadWithSelectedIdFallback,
  copyReferenceForRawSelectorSelection,
  copyReferenceForStepTreeNodeSelection,
  copyableStepTreeNodeForWorkspace
} from "./stepTreeSelection.js";

// What a STEP copies: the references a selection, or one tree node, resolves to, as the text
// Copy Reference puts on the clipboard. Pure: the surface hands in what its references are
// resolved through, as it stands.

/**
 * @typedef {{ entry: object, isAssemblyView: boolean, copyReferenceMap: Map<string, object>,
 *   referenceMap: Map<string, object>, assemblyPartMap: Map<string, object>, displayRoot: object | null,
 *   root: object | null }} StepCopyContext
 */

const topologyReference = (context, id) => context.copyReferenceMap.get(id) || context.referenceMap.get(id) ||
  copyReferenceForRawSelectorSelection(id, "topology");
const treeNode = (context, id) => copyableStepTreeNodeForWorkspace({
  assemblyPartMap: context.assemblyPartMap, displayStepTreeRoot: context.displayRoot, stepTreeRoot: context.root, nodeId: id
});

/**
 * The copy payload for a selection: its faces and edges, then its parts (a part's own selector,
 * else its tree node's), with the whole file standing for a single part's root.
 *
 * @param {StepCopyContext} context
 * @param {{ referenceIds: string[], partIds: string[] }} selection
 */
export function selectionCopyPayload(context, { referenceIds, partIds }) {
  const references = referenceIds.map((id) => topologyReference(context, id)).filter(Boolean);
  if (!context.isAssemblyView && partIds.includes(STEP_MODEL_ROOT_ID)) {
    const whole = buildWholeStepEntryCopyReference(context.entry);
    if (whole) references.push(whole);
  }
  const parts = partIds.map((id) => copyReferenceForRawSelectorSelection(id, "assembly-part") ||
    context.copyReferenceMap.get(id) ||
    copyReferenceForStepTreeNodeSelection(treeNode(context, id), id, "assembly-part")).filter(Boolean);
  return copyPayloadWithSelectedIdFallback(buildSelectionCopyPayload({ references: [...references, ...parts], parts: [], entry: context.entry }), {
    selectedReferenceIds: referenceIds, selectedPartIds: partIds, copyReferenceMap: context.copyReferenceMap
  });
}
