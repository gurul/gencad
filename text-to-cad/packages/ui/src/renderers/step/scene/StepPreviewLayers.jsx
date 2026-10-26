import { useMemo, useRef } from "react";
import { VIEWER_PICK_MODE } from "@text-to-cad/core/lib/viewer/constants.js";
import { AnimationClockProvider } from "../workbench/animationClockStore.js";
import StepSceneLayers from "./StepSceneLayers.jsx";
import { useStepViewPolicy } from "./useStepViewPolicy.js";

const EMPTY_LIST = Object.freeze([]);
const EMPTY_OVERRIDES = Object.freeze({});
const NO_HOVER = Object.freeze({ hoveredPartId: "", hoveredReferenceId: "" });
const NOTHING_HOVERED = () => NO_HOVER;

/**
 * Preview's STEP scene, driven from inside Preview's own viewport (`PreviewView.jsx`):
 * the same layers the editor mounts (`StepSceneLayers.jsx`), a second instance, over Preview's
 * own scene (`previewStepScene`), which the same builder fills from the same published mesh, so it
 * shares the editor's component geometry (core's owner counts) and dresses its own materials.
 *
 * It draws the Render scene Preview draws (`drawn`), at Preview's quality, its pose and its
 * routine Preview's own (`motion`, `useStepPreviewMotion`) on Preview's clock, and nothing
 * else: no selection, hover, measure, knobs, section or explode, nothing to pick. It reports to no
 * one but the detail loader's camera (`onLodCameraChange`): the editor's instance alone answers
 * the loader's adoption protocol, the file's alerts and its memory accounting.
 */
export default function StepPreviewLayers({ viewport, drawn, previewStepScene, meshData, modelKey, isLoading,
  selectorRuntime, stepParameterRuntime, motion, renderPartsIndividually, hoverStore, onLodCameraChange }) {
  const api = useRef(null);
  const policy = useStepViewPolicy({
    meshData, themeSettings: drawn.theme, displaySettings: drawn.display,
    renderMode: drawn.render.enabled, renderConfiguration: drawn.render.configuration,
    renderPartsIndividually: renderPartsIndividually || Boolean(motion.animationRuntime?.clip),
    pickMode: VIEWER_PICK_MODE.NONE, pickableParts: EMPTY_LIST, pickableFaces: EMPTY_LIST, pickableEdges: EMPTY_LIST,
    hiddenPartIds: EMPTY_LIST, selectedPartIds: EMPTY_LIST, focusedPartId: EMPTY_LIST
  });
  const parameterRuntime = useMemo(() => (stepParameterRuntime
    ? { ...stepParameterRuntime, parameterValues: motion.parameterValues } : null), [stepParameterRuntime, motion.parameterValues]);
  const props = {
    preview: true,
    stepParameterRuntime: parameterRuntime,
    hiddenPartIds: EMPTY_LIST, focusedPartIds: EMPTY_LIST, selectedPartIds: EMPTY_LIST, selectedReferenceIds: EMPTY_LIST,
    resolveHover: NOTHING_HOVERED, hoverStore, jointHandles: null,
    measureState: null, activeMeasurementId: "", selectedMeasurementIds: EMPTY_LIST, hoveredMeasurementId: "", measureModeActive: false,
    meshData, modelKey, isLoading,
    renderMode: drawn.render.enabled,
    renderConfiguration: drawn.render.configuration,
    appearance: drawn.appearance,
    materialOverrides: drawn.materialOverrides || EMPTY_OVERRIDES,
    receiveShadows: drawn.view.lighting.enabled,
    pickMode: VIEWER_PICK_MODE.NONE,
    pickableParts: EMPTY_LIST,
    selectorRuntime,
    stepAnimationRuntime: motion.animationRuntime,
    animateMode: true,
    onLodCameraChange,
    onMeshSourceAdoption: null,
    onViewerAlertChange: null,
    onHoverReferenceChange: null, onActivateReference: null, onDoubleActivateReference: null,
    onMeasurePick: null, onMeasureHoverPoint: null,
    deferActivation: false,
    pickAtRef: null,
    topologyAtRef: null
  };
  return <AnimationClockProvider value={motion.clock}>
    <StepSceneLayers viewport={viewport} stepScene={previewStepScene} policy={policy} props={props} api={api} />
  </AnimationClockProvider>;
}
