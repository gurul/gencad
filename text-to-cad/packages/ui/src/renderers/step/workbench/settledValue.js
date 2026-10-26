import { useEffect, useRef, useState } from "react";

// A value that follows another in a few grouped steps rather than every change: Preview's
// scene takes finer detail this way (`StepSurface.jsx`). Each change Preview's scene adopts
// starts its converging picture again, and the detail loader publishes a large model's finer
// detail as a burst of batches; taken as they come, the picture restarts with each of them and
// never settles while they stream. Taken once the stream has been quiet for `quietMs`, or every
// `maxWaitMs` while it keeps going, a burst of fifteen costs one or two restarts.

/**
 * The scheduling, without React: `offer(value)` for every change; `onValue(value)` is called with
 * the newest one once changes have been quiet for `quietMs`, or `maxWaitMs` after the first one
 * not yet handed on, whichever is sooner.
 */
export function createSettledValue({ quietMs = 300, maxWaitMs = 1000, onValue,
  setTimeoutFn = (...args) => setTimeout(...args), clearTimeoutFn = handle => clearTimeout(handle), now = () => Date.now() }) {
  let pending = undefined, has = false, firstAt = 0, timer = null;
  const flush = () => {
    timer = null;
    if (!has) return;
    const value = pending;
    has = false; pending = undefined;
    onValue(value);
  };
  return {
    offer(value) {
      if (!has) firstAt = now();
      pending = value; has = true;
      if (timer !== null) clearTimeoutFn(timer);
      timer = setTimeoutFn(flush, Math.max(0, Math.min(quietMs, firstAt + maxWaitMs - now())));
    },
    dispose() { if (timer !== null) clearTimeoutFn(timer); timer = null; has = false; },
  };
}

/**
 * `value` as it was last handed on (`createSettledValue`) while `grouped`; `value` itself while
 * not, and in the render grouping starts in.
 */
export function useSettledValue(value, { grouped = false, quietMs = 300, maxWaitMs = 1000 } = {}) {
  const [settled, setSettled] = useState({ grouped, value });
  // Grouping starts from the value as it is, in the same render.
  if (settled.grouped !== grouped) setSettled({ grouped, value });
  const scheduler = useRef(null);
  useEffect(() => {
    if (!grouped) return undefined;
    const current = createSettledValue({ quietMs, maxWaitMs, onValue: next => setSettled(state => ({ ...state, value: next })) });
    scheduler.current = current;
    return () => { current.dispose(); if (scheduler.current === current) scheduler.current = null; };
  }, [grouped, quietMs, maxWaitMs]);
  const offered = useRef(value);
  useEffect(() => {
    if (offered.current === value) return;
    offered.current = value;
    if (grouped) scheduler.current?.offer(value);
  }, [grouped, value]);
  return grouped && settled.grouped ? settled.value : value;
}
