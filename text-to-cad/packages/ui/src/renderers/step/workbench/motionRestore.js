import { normalizeParameterValues } from "@text-to-cad/core/common/parameters.js";
import { buildDefaultAnimationState, restoreAnimationState } from "@text-to-cad/core/common/animationClock.js";

// A model can be posed by Position or by a routine. The owner in hand wins: while a routine
// owns the pose, the Position values are not applied under it.
export function restoreMotionParameters(definition, values, animation) {
  const animationOwnsPose = animation?.enabled !== false && Boolean(animation?.activeClipId);
  return normalizeParameterValues(definition,
    animationOwnsPose ? definition?.defaultParameterValues : values || definition?.defaultParameterValues);
}

// The animation state carried across a load, reconciled against the clips this model actually
// compiled. A routine never resumes: every open, and every reload of the clips, starts at rest, the
// pose Position's until preview plays the routine.
export function restoreMotionAnimation(current, clips) {
  const restored = restoreAnimationState(current, clips);
  return { ...restored, enabled: false, playing: false, elapsedSec: 0 };
}

/** A model's animation state before anything is played: its first routine chosen, at rest. */
export function restingAnimationState(clips) {
  return { ...buildDefaultAnimationState(clips), enabled: false };
}
