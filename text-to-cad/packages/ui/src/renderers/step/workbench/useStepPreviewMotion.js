import { useLayoutEffect, useMemo, useRef, useState } from "react";
import { animationClipList, animationRenderFrame, findAnimationClip } from "@text-to-cad/core/common/animationClock.js";
import { normalizeParameterValues } from "@text-to-cad/core/common/parameters.js";
import { tolerantAnimationClip } from "../components/workbench/hooks/packageProgressiveLoad.js";
import { createAnimationClock } from "./animationClockStore.js";
import { restingAnimationState, restoreMotionAnimation } from "./motionRestore.js";
import { motionSectionControls } from "./useStepMotion.js";
import { useStepMotionControls } from "./useStepMotionControls.js";

/**
 * Preview's own motion: a pose and a routine of its own over the same kinematics module
 * and routines the tools view loaded (`useStepMotion`), played on Preview's own scene with its
 * own clock. Nothing of it reaches the tools view, and nothing of the tools view reaches it: each
 * time Preview opens (`open` turns true) it starts from the model as authored, at rest, its
 * first routine chosen and not playing.
 *
 * @param {{ definition: object | null, clips: object | null, meshPartial: boolean, open: boolean }} options
 * @returns {{ positionControls: object, animationControls: object, parameterValues: object,
 *   animationRuntime: object | null, clock: object }}
 */
export function useStepPreviewMotion({ definition, clips, meshPartial = false, open = false }) {
  const [clock] = useState(createAnimationClock);
  const resting = () => restoreMotionAnimation(restingAnimationState(clips), clips || {});
  const defaults = () => normalizeParameterValues(definition, definition?.defaultParameterValues || {});
  const [parameterValues, setParameterValues] = useState(defaults);
  const [animationState, setAnimationState] = useState(resting);
  const [appliedPoseName, setAppliedPoseName] = useState("");
  const parameterValuesRef = useRef(parameterValues);
  const animationStateRef = useRef(animationState);
  const motionRevisionRef = useRef(0);

  // At rest on every opening, and whenever what it moves changes under it: before anything (an
  // Autoplay) plays it.
  useLayoutEffect(() => {
    if (!open) return;
    const values = defaults();
    parameterValuesRef.current = values;
    setParameterValues(values);
    const state = resting();
    animationStateRef.current = state;
    setAnimationState(state);
    setAppliedPoseName("");
    clock.resetAnimationClock();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, definition, clips]);

  const clipList = useMemo(() => animationClipList(clips), [clips]);
  const activeClip = useMemo(() => findAnimationClip(clips, animationState.activeClipId), [clips, animationState.activeClipId]);
  const playableClip = useMemo(() => (meshPartial ? tolerantAnimationClip(activeClip) : activeClip), [activeClip, meshPartial]);
  const animationRuntime = useMemo(() => animationRenderFrame({
    enabled: animationState.enabled !== false,
    clip: playableClip,
    elapsedSec: animationState.elapsedSec,
    playing: animationState.playing
  }), [animationState.elapsedSec, animationState.enabled, animationState.playing, playableClip]);

  const commands = useStepMotionControls({
    selectedStepModuleDefinition: definition, selectedAnimationClips: clips, selectedActiveAnimationClip: activeClip,
    animationState, animationStateRef, setAnimationState, stepModuleParameterValuesRef: parameterValuesRef,
    setStepModuleParameterValues: setParameterValues, setAppliedStepPoseName: setAppliedPoseName, motionRevisionRef, clock
  });
  const { positionControls, animationControls } = motionSectionControls({
    status: definition ? "ready" : "idle", error: "", definition, parameterValues, appliedPoseName, animationRuntime,
    animationStatus: clips ? "ready" : "idle", animationError: "", clipList, animationState, commands, clock
  });
  return { positionControls, animationControls, parameterValues, animationRuntime, clock };
}
