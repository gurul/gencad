import { useAnimationClockValue } from "./animationClock.js";
import { Slider } from "@text-to-cad/ui/primitives/slider";
import { FILE_SHEET_PRECISION_SLIDER_CLASSES } from "../../inspector/FileSheet.js";

// The file sidebar's Animation section (`AnimationSection.jsx`) is the one transport, in the tools
// view and Preview alike: the routine, Play/Pause, this scrubber and the Playback settings
// (`PlaybackMenu.jsx`).
//
// Every animation source shares this transport UI. It only edits the clip and clock state of
// the runtime it is handed; evaluating a clip is its owner's.
//
// runtime: { clips: [{ id, label, duration }], activeClipId, playing, elapsedSec,
//   speed, loopEnabled, clock, onClipSelect, onPlayToggle, onScrub, onSpeedChange,
//   onLoopToggle, onRelease }. `clock` is the owner's live AnimationClock (`animationClock.js`);
//   `onRelease` stops, rewinds and puts the model back at rest, as crossing into or out of Preview does.

export const PLAYBACK_SPEEDS = [0.25, 0.5, 0.75, 1, 1.5, 2, 3];

export function formatSeconds(value) {
  const numericValue = Math.max(Number(value) || 0, 0);
  return `${numericValue.toFixed(numericValue >= 10 ? 1 : 2)}s`;
}

/**
 * The scrubber over the routine in hand. It tracks the LIVE clock while playing: the elapsed time on
 * the runtime snapshot only moves when playback stops, because a playing clip publishes through the
 * clock store instead of React state.
 */
export function AnimationTimeControl({ runtime, disabled = false, className = FILE_SHEET_PRECISION_SLIDER_CLASSES }) {
  const activeClip = runtime?.clips?.find(clip => clip.id === runtime?.activeClipId);
  const duration = Math.max(Number(activeClip?.duration) || 1, 0.001);
  const liveElapsedSec = useAnimationClockValue(runtime?.clock);
  const rawElapsedSec = runtime?.playing === true ? liveElapsedSec : runtime?.elapsedSec;
  const value = Math.min(Math.max(Number(rawElapsedSec) || 0, 0), duration);
  return (
    <Slider
      className={className}
      disabled={disabled}
      value={[value]}
      min={0}
      max={duration}
      step={0.01}
      onValueChange={(nextValue) => runtime?.onScrub?.(nextValue?.[0] ?? 0)}
      thumbProps={{ "aria-label": "Animation time", "aria-valuetext": `${formatSeconds(value)} of ${formatSeconds(duration)}` }}
    />
  );
}

/** A file has animation when it has routines to play: no routines, no Animation section. */
export function animationControlsHaveContent(runtime) {
  return Array.isArray(runtime?.clips) && runtime.clips.length > 0;
}
