import PoseControlsSection, { poseControlsHaveContent } from "./PoseControlsSection.js";

// The Position section for STEP (the file sidebar's, whatever the tool): its
// named poses (Default among them, which puts the joints back) and its joint values. Animation is a tool of its
// own (in preview too), not a section, so a file with routines and no joints has no
// Position at all. One host command still resets all motion, including pending playback and pose frames.
export function buildPositionSection({ poseRuntime = null } = {}) {
  if (!poseControlsHaveContent(poseRuntime)) return null;
  return {
    id: "position",
    title: "Position",
    content: (
      <div className="space-y-1.5 pb-1.5 pt-0.5">
        <PoseControlsSection runtime={poseRuntime} />
      </div>
    ),
  };
}
