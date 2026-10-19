import assert from "node:assert/strict";
import test from "node:test";
import { createSettledValue } from "./settledValue.js";

// A test clock: timers fire as `advance` passes them.
function clock() {
  let time = 0, next = 1;
  const timers = new Map();
  return {
    now: () => time,
    setTimeoutFn: (fn, ms) => { timers.set(next, { at: time + ms, fn }); return next++; },
    clearTimeoutFn: id => { timers.delete(id); },
    advance(ms) {
      const end = time + ms;
      for (;;) {
        const due = [...timers.entries()].filter(([, timer]) => timer.at <= end).sort((a, b) => a[1].at - b[1].at)[0];
        if (!due) break;
        timers.delete(due[0]); time = due[1].at; due[1].fn();
      }
      time = end;
    }
  };
}

test("a burst of detail reaches Preview's scene as a few grouped steps: after a quiet moment, or at the longest wait", () => {
  const time = clock();
  const handed = [];
  const settled = createSettledValue({ quietMs: 300, maxWaitMs: 1000, onValue: value => handed.push(value), ...time });
  // Fifteen batches 100 ms apart: never quiet for 300 ms, so the longest wait hands on the newest.
  for (let batch = 1; batch <= 15; batch += 1) { settled.offer(batch); time.advance(100); }
  time.advance(300);
  assert.deepEqual(handed, [10, 15], "fifteen batches, two steps");
  // A lone batch goes on once the stream has been quiet.
  settled.offer(16);
  time.advance(299);
  assert.deepEqual(handed, [10, 15]);
  time.advance(1);
  assert.deepEqual(handed, [10, 15, 16]);
  settled.dispose();
});
