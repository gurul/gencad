import assert from "node:assert/strict";
import test from "node:test";

import { selects, toggleSelectAll, toggleSelectFilter } from "./selectFilter.js";

const KINDS = ["parts", "faces", "edges", "position", "annotation", "measurement"];

test("each kind is ticked and unticked on its own, every one of them off if need be", () => {
  assert.deepEqual(toggleSelectFilter(KINDS, "faces", false), ["parts", "edges", "position", "annotation", "measurement"]);
  assert.deepEqual(toggleSelectFilter(["edges"], "faces", true), ["edges", "faces"]);
  assert.deepEqual(toggleSelectFilter(["faces"], "faces", true), ["faces"], "ticking a ticked kind keeps it once");
  assert.deepEqual(toggleSelectFilter(["links"], "links", false), []);
});

test("Select all ticks every kind, and with every kind ticked already, none", () => {
  assert.deepEqual(toggleSelectAll([], KINDS), KINDS);
  assert.deepEqual(toggleSelectAll(["faces", "position"], KINDS), KINDS);
  assert.deepEqual(toggleSelectAll(KINDS, KINDS), []);
  // A kind the menu does not offer (Parts in a part file) is not needed for "every kind".
  assert.deepEqual(toggleSelectAll(KINDS, ["faces", "edges"]), []);
});

test("a filter picks what it ticks", () => {
  assert.equal(selects(["faces", "measurement"], "measurement"), true);
  assert.equal(selects(["faces"], "measurement"), false);
  assert.equal(selects([], "faces"), false);
});
