import { useCallback, useEffect, useRef } from "react";
import { advanceAnimationElapsed, animationClipDuration, animationNowMs,
  clampAnimationElapsed, clampAnimationSpeed, createAnimationFramePacer, findAnimationClip,
  firstAnimationClipId } from "@text-to-cad/core/common/animationClock.js";
import { normalizeParameterValue, normalizeParameterValues } from "@text-to-cad/core/common/parameters.js";
import { poseValuesForPreset } from "../components/workbench/PoseControlsSection.js";

// Single command boundary for STEP motion. Refs are published synchronously so
// queued playback callbacks cannot resurrect the previous motion owner.
//
// One of four at a time: Explode, Clip, Position and a routine's frame replace each other, the
// others going back to their defaults when one is SET (its value changed; a tool taken up or a
// panel pressed changes nothing) — nothing is set aside to come back. Position and the routine are
// both here; Explode and Clip are the host's view settings, so `host.onUse(motion)` tells it which
// of these two was used ("position" or "animation") and it takes Explode and Clip off. The tools view and Preview each have their own motion
// (`useStepMotion`, `useStepPreviewMotion`): their own values, their own routine and its `clock`.
export function useStepMotionControls({
  selectedStepModuleDefinition, selectedAnimationClips, selectedActiveAnimationClip,
  animationState, animationStateRef, setAnimationState, stepModuleParameterValuesRef,
  setStepModuleParameterValues, setAppliedStepPoseName, motionRevisionRef, clock, host = null
}) {
  const hostRef = useRef(host);
  hostRef.current = host;
  const { getAnimationClock, setAnimationClock, resetAnimationClock } = clock;
  const writeParameters = useCallback((values) => {
    const current = stepModuleParameterValuesRef.current;
    // Scrubbing/speed edits must not reapply the kinematics tree on every event
    // after animation already owns an authored pose.
    if (current && Object.keys(current).length === Object.keys(values).length &&
      Object.keys(values).every(key => Object.is(current[key], values[key]))) return;
    stepModuleParameterValuesRef.current = values;
    setStepModuleParameterValues(values);
  }, [stepModuleParameterValuesRef, setStepModuleParameterValues]);
  const resetPosition = useCallback(() => {
    setAppliedStepPoseName("");
    writeParameters(normalizeParameterValues(selectedStepModuleDefinition, selectedStepModuleDefinition?.defaultParameterValues || {}));
  }, [selectedStepModuleDefinition, setAppliedStepPoseName, writeParameters]);
  // The routine back to rest: stopped, its clock rewound, the pose no longer its. Nothing more: the
  // transport preferences (the routine, its speed, the loop) are the person's, kept for the next play.
  const rewindAnimation = useCallback(() => {
    motionRevisionRef.current += 1;
    const current = animationStateRef.current;
    if (current.enabled === false && !current.playing && !current.elapsedSec) return;
    const next = { ...current, enabled: false, playing: false, elapsedSec: 0 };
    animationStateRef.current = next;
    setAnimationState(next);
    resetAnimationClock();
  }, [resetAnimationClock]);
  // Position used — a joint, a value, a named pose: the routine goes back to rest, and the host
  // takes Explode off.
  const claimPosition = useCallback(() => {
    rewindAnimation();
    hostRef.current?.onUse?.("position");
  }, [rewindAnimation]);
  // A routine used — played, scrubbed, rewound: it plays from the model at rest, so the pose goes
  // back to its default, and the host takes Explode off.
  const claimAnimation = useCallback(() => {
    motionRevisionRef.current += 1;
    resetPosition();
    hostRef.current?.onUse?.("animation");
  }, [resetPosition]);
  // The model at rest: the default pose and the routine rewound. Position's Reset, and what using
  // Explode does to the other two.
  const resetMotion = useCallback(() => {
    rewindAnimation();
    resetPosition();
  }, [rewindAnimation, resetPosition]);
  const handleStepModuleParameterChange = useCallback((parameterId, value) => {
    const id = String(parameterId || "").trim();
    const control = selectedStepModuleDefinition?.parameters?.find(parameter => parameter.id === id);
    if (!control) {
      return;
    }
    claimPosition();
    // Moving a control by hand leaves the named pose behind, so the dropdown stops claiming
    // it and goes back to reading the values (the robot's group state does the same).
    setAppliedStepPoseName("");
    writeParameters({ ...stepModuleParameterValuesRef.current, [id]: normalizeParameterValue(control, value) });
  }, [claimPosition, selectedStepModuleDefinition, writeParameters]);

  const applyStepModuleParameterValues = useCallback((values) => {
    if (!selectedStepModuleDefinition) return;
    claimPosition();
    setAppliedStepPoseName("");
    writeParameters(normalizeParameterValues(selectedStepModuleDefinition, { ...stepModuleParameterValuesRef.current, ...values }));
  }, [claimPosition, selectedStepModuleDefinition, writeParameters]);
  const handleResetStepModuleParameters = resetMotion;

  const handleApplyPose = useCallback((poseName) => {
    if (!selectedStepModuleDefinition?.manifest?.poses?.[poseName]) {
      return;
    }
    claimPosition();
    const nextParameterValues = poseValuesForPreset(selectedStepModuleDefinition, poseName);
    setAppliedStepPoseName(String(poseName || ""));
    // A pose is written like any other value: where the mechanism is from this
    // frame on. Motion over time belongs to preview mode.
    writeParameters(nextParameterValues);
  }, [claimPosition, selectedStepModuleDefinition, setAppliedStepPoseName, writeParameters]);

  // Choosing a routine puts it at its start, at rest: it is not a use of it until it plays or is
  // scrubbed, so the pose and Explode stay as they are.
  const handleAnimationClipSelect = useCallback((clipId) => {
    const clip = findAnimationClip(selectedAnimationClips, clipId);
    if (!clip) {
      // The picker only ever offers clips this model ships, so an id that does
      // not resolve is a stale event, not a request to idle the transport —
      // pausing is handled by the transport.
      return;
    }
    motionRevisionRef.current += 1;
    const nextState = {
      ...animationStateRef.current,
      activeClipId: clip.id,
      enabled: false,
      playing: false,
      elapsedSec: 0,
      // The loop preference follows the newly-selected clip's own default.
      loopEnabled: clip.loop !== false
    };
    animationStateRef.current = nextState;
    setAnimationState(nextState);
    resetAnimationClock();
  }, [selectedAnimationClips]);

  const handleAnimationPlayToggle = useCallback(() => {
    const currentState = animationStateRef.current;
    // A GUARD, not a UI path: once the clips compile the selection is always one
    // of them (the default picks clip 0, a restore falls back to clip 0, and the
    // picker only offers ids that resolve), and before they compile there are no
    // clips to find at all, so both lookups miss and this returns below. It
    // stays because Play doing nothing would be the silent failure — if a
    // selection ever went empty with clips in hand, Play should start the first
    // one rather than shrug.
    const clip = findAnimationClip(selectedAnimationClips, currentState.activeClipId)
      || findAnimationClip(selectedAnimationClips, firstAnimationClipId(selectedAnimationClips));
    if (!clip) {
      return;
    }
    claimAnimation();
    const duration = animationClipDuration(clip);
    if (currentState.playing) {
      const nextState = {
        ...currentState,
        activeClipId: clip.id,
        elapsedSec: clampAnimationElapsed(getAnimationClock(), duration),
        playing: false
      };
      animationStateRef.current = nextState;
      setAnimationState(nextState);
      return;
    }
    // Resuming from the end of a non-looping clip restarts it; there is nowhere
    // else for the clock to go.
    const elapsedSec = currentState.elapsedSec >= duration
      ? 0
      : clampAnimationElapsed(currentState.elapsedSec, duration);
    // Play takes ownership of the pose from the independent Position controls.
    const nextState = {
      ...currentState,
      activeClipId: clip.id,
      enabled: true,
      elapsedSec,
      playing: true
    };
    animationStateRef.current = nextState;
    setAnimationState(nextState);
    setAnimationClock(elapsedSec);
  }, [selectedAnimationClips, claimAnimation]);

  const handleAnimationRestart = useCallback(() => {
    if (!selectedActiveAnimationClip) return;
    claimAnimation();
    const nextState = {
      ...animationStateRef.current,
      enabled: true,
      elapsedSec: 0,
      playing: false
    };
    animationStateRef.current = nextState;
    setAnimationState(nextState);
    resetAnimationClock();
  }, [selectedActiveAnimationClip, claimAnimation]);

  const handleAnimationScrub = useCallback((elapsedSec) => {
    const clip = selectedActiveAnimationClip;
    if (!clip) {
      return;
    }
    claimAnimation();
    const clampedElapsedSec = clampAnimationElapsed(elapsedSec, animationClipDuration(clip));
    const nextState = {
      ...animationStateRef.current,
      enabled: true,
      elapsedSec: clampedElapsedSec
    };
    animationStateRef.current = nextState;
    setAnimationState(nextState);
    setAnimationClock(clampedElapsedSec);
  }, [selectedActiveAnimationClip, claimAnimation]);

  // Speed and Loop are how the routine plays, not a use of it: the pose and its frame stay.
  const handleAnimationSpeedChange = useCallback((speed) => {
    if (!selectedActiveAnimationClip) return;
    const nextState = { ...animationStateRef.current, speed: clampAnimationSpeed(speed) };
    animationStateRef.current = nextState;
    setAnimationState(nextState);
  }, [selectedActiveAnimationClip]);

  const handleAnimationLoopToggle = useCallback((nextLoopEnabled) => {
    if (!selectedActiveAnimationClip) return;
    const currentState = animationStateRef.current;
    const nextState = {
      ...currentState,
      loopEnabled: typeof nextLoopEnabled === "boolean" ? nextLoopEnabled : !currentState.loopEnabled
    };
    animationStateRef.current = nextState;
    setAnimationState(nextState);
  }, [selectedActiveAnimationClip]);

  // The playback loop. The clock is published through the external store rather
  // than React state so a playing clip re-renders only the render pane and the
  // time slider; the paused elapsed time is written back to React state once,
  // when playback stops. Frame pacing (createAnimationFramePacer) keeps a heavy
  // assembly from saturating the main thread, and only a run of overrunning
  // frames is saturation: one that misses a vsync publishes on.
  useEffect(() => {
    if (
      !selectedActiveAnimationClip ||
      animationState.enabled === false ||
      !animationState.playing ||
      typeof window === "undefined" ||
      typeof window.requestAnimationFrame !== "function"
    ) {
      return undefined;
    }

    const clip = selectedActiveAnimationClip;
    const duration = animationClipDuration(clip);
    let frameId = 0;
    let cancelled = false;
    let previousTimeMs = animationNowMs();
    // A published frame is measured by the gap to the next callback, which
    // includes the downstream render; once the last few all overran, the next
    // publish waits about twice that. previousTimeMs only advances on a publish,
    // so time skipped this way still lands in the next delta and playback stays
    // wall-clock accurate.
    const pacer = createAnimationFramePacer();
    setAnimationClock(clampAnimationElapsed(animationStateRef.current.elapsedSec, duration));

    const tick = (timeMs) => {
      const currentState = animationStateRef.current;
      if (cancelled || currentState.enabled === false || !currentState.playing || currentState.activeClipId !== clip.id) {
        return;
      }
      if (!pacer.shouldPublish(timeMs)) {
        frameId = window.requestAnimationFrame(tick);
        return;
      }
      const deltaSec = Math.max((timeMs - previousTimeMs) / 1000, 0);
      previousTimeMs = timeMs;
      pacer.published(timeMs);
      const { elapsedSec, playing } = advanceAnimationElapsed({
        elapsedSec: getAnimationClock(),
        deltaSec,
        speed: currentState.speed,
        duration,
        loopEnabled: currentState.loopEnabled !== false
      });
      setAnimationClock(elapsedSec);
      if (!playing) {
        // A non-looping clip ran out: settle the clock into React state so the
        // paused transport and the session snapshot agree with the viewport.
        const nextState = { ...currentState, elapsedSec, playing: false };
        animationStateRef.current = nextState;
        setAnimationState(nextState);
        return;
      }
      frameId = window.requestAnimationFrame(tick);
    };

    frameId = window.requestAnimationFrame(tick);
    return () => {
      cancelled = true;
      window.cancelAnimationFrame(frameId);
    };
  }, [animationState.enabled, animationState.playing, selectedActiveAnimationClip]);

  // Back to rest: the routine stopped and rewound, the model as Position has it. Its Reset.
  const releaseAnimation = rewindAnimation;

  return { handleStepModuleParameterChange, applyStepModuleParameterValues, handleResetStepModuleParameters,
    handleApplyPose, handleAnimationClipSelect, handleAnimationPlayToggle, handleAnimationRestart,
    handleAnimationScrub, handleAnimationSpeedChange, handleAnimationLoopToggle, resetMotion, resetPosition,
    releaseAnimation };
}
