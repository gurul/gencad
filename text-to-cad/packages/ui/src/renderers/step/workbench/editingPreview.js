// A tab's view of the build feed for its file: whether a build is running, how far it has got and
// whether it failed. Never geometry: the view always shows the saved file, updated in place when
// the build writes it (STORE.md 9b).
export const BUILDING_STATES = Object.freeze(["submitted", "queued", "building"]);

export function initialEditingPreview() {
  return {
    epoch: "",
    revision: 0,
    superseded: false,
    state: "disconnected",
    phase: "",
    detail: "",
    updatedAt: 0,
    error: "",
  };
}

/** Whether a build of the file is queued or running. */
export function editingBuildActive(state) {
  return BUILDING_STATES.includes(state?.state);
}

export function reduceEditingPreview(current, next) {
  if (!next || typeof next !== "object") return current;
  if (!next.epoch) {
    return { ...current, state: "disconnected", phase: "", detail: "", updatedAt: 0, error: next.error || "" };
  }
  const previous = current.epoch && current.epoch !== next.epoch ? initialEditingPreview() : current;
  const revision = Number(next.revision) || 0;
  if (revision < previous.revision) return current;
  const same = revision === previous.revision;
  const state = next.state || "building";
  const active = BUILDING_STATES.includes(state);
  // A build the file moved past (the server's `superseded`): its failure is no longer the news.
  const superseded = next.superseded === true;
  return {
    epoch: next.epoch,
    revision,
    superseded,
    state,
    phase: active ? String(next.phase || (same ? previous.phase : "") || "").trim() : "",
    detail: active ? String(next.detail || (same ? previous.detail : "") || "").trim() : "",
    updatedAt: active ? Number(next.updatedAt) || (same ? previous.updatedAt : 0) || 0 : 0,
    error: superseded ? "" : next.error || "",
    output: next.output,
    file: next.file || next.output,
  };
}
