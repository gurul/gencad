import { useEffect, useMemo, useState } from "react";
import { initialEditingPreview, reduceEditingPreview } from "../../../workbench/editingPreview.js";
import { observeEditingPreview } from "../../../workbench/editingPreviewFeed.js";

// The build feed's status for `file`. The view shows the saved file; when a build finishes, or the
// file moves past one, the catalog is read at once, so the saved file replaces the one on screen
// without waiting for the catalog's next poll.
export function useEditingPreview(file, { enabled, client } = {}) {
  const [snapshot, setSnapshot] = useState(() => ({ file: "", state: initialEditingPreview() }));
  useEffect(() => {
    if (!enabled || !file) return undefined;
    // A poll that changes nothing, a failed one included, keeps the snapshot: the surface re-renders
    // only for news, not once per poll while the feed is down.
    const apply = next => setSnapshot(previous => {
      const before = previous.file === file ? previous.state : initialEditingPreview();
      const state = reduceEditingPreview(before, next);
      return previous.file === file && JSON.stringify(before) === JSON.stringify(state)
        ? previous : { file, state };
    });
    return observeEditingPreview(file, apply, error => apply({ error: error.message }), { client });
  }, [file, enabled, client]);
  const state = useMemo(() => enabled && snapshot.file === file
    ? snapshot.state : initialEditingPreview(), [enabled, file, snapshot]);
  const settled = state.superseded === true || state.state === "done";
  useEffect(() => {
    if (settled && file) void client?.refresh?.({ file, markRefreshing: false })?.catch?.(() => {});
  }, [settled, file, client, state.revision]);
  return { state };
}
