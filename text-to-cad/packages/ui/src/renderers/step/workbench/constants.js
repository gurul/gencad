export const ASSET_STATUS = {
  PENDING: "pending",
  LOADING: "loading",
  READY: "ready",
  ERROR: "error"
};

export const REFERENCE_STATUS = {
  IDLE: "idle",
  DISABLED: "disabled",
  LOADING: "loading",
  READY: "ready",
  ERROR: "error"
};

import { createToolModes } from "../../kit/tools/toolModes.js";

export const TAB_TOOL_MODE = {
  REFERENCES: "references",
  PENCIL: "pencil",
  SHAPES: "shapes",
  MEASURE: "measure",
  EXPLODE: "exploded",
  CLIP: "clip"
};


// This renderer's tool modes for the kit's state machine (`kit/tools/toolModes.js`).
// Pencil, Shapes and Animation toggle off on repeated activation. Measure stays armed; its result-aware
// toolbar action clears retained measurements explicitly. The tool in hand is never
// saved: a file opens in Select, with its pose intact. Position is Select's: its knobs,
// while Select's filter picks it.
export const CAD_TOOL_MODES = createToolModes({
  defaultMode: TAB_TOOL_MODE.REFERENCES,
  modes: {
    [TAB_TOOL_MODE.REFERENCES]: {},
    [TAB_TOOL_MODE.MEASURE]: {},
    [TAB_TOOL_MODE.EXPLODE]: {},
    [TAB_TOOL_MODE.CLIP]: {},
    [TAB_TOOL_MODE.PENCIL]: {},
    [TAB_TOOL_MODE.SHAPES]: {}
  }
});
