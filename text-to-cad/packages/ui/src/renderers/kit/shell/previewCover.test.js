import assert from "node:assert/strict";
import test from "node:test";
import { detailStillComing, previewCoverStep } from "./previewCover.js";

test("a detail restart is not motion: a picture started again by finer detail is waited for, never lifted on", () => {
  // Detail landed: the picture fell from sample 9 back to 1. Nothing moves the view.
  assert.equal(previewCoverStep({ presented: true, refining: false, moving: false, progress: { sample: 1, samples: 32 } }), "converge");
  assert.equal(previewCoverStep({ presented: true, refining: false, moving: false, progress: { sample: 32, samples: 32 } }), "lift");
  // An orbit or a routine starts the picture every frame: there is nothing to wait for.
  assert.equal(previewCoverStep({ presented: true, refining: false, moving: true, progress: { sample: 0, samples: 32 } }), "lift");
  // A view that draws no studio frame (lighting off, software WebGL) lifts once it has presented.
  assert.equal(previewCoverStep({ presented: true, refining: false, moving: false, progress: null }), "lift");
});

test("the cover waits for Preview's first frame and for detail still on its way, preview detail included", () => {
  assert.equal(previewCoverStep({ presented: false, refining: false, moving: true, progress: null }), "wait");
  assert.equal(previewCoverStep({ presented: true, refining: true, moving: false, progress: { sample: 32, samples: 32 } }), "wait");
  assert.deepEqual(["preview", "refining", "standard", "high", "limited", "error", null].map(detailStillComing),
    [true, true, false, false, false, false, false]);
});
