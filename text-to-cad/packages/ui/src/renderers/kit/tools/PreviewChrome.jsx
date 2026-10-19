import { ToolbarTooltipScope } from "@text-to-cad/ui/primitives/toolbar-button";
import { VIEWPORT_INSET_PX } from "../shell/viewportLayout.js";

/**
 * The viewer's chrome around Preview. `children` — the tool strip and its stack,
 * Quick Edit, everything a person edits with — is hidden and inert while `active`. The navbar stays
 * (the way to other files); the tool strip steps aside, and Preview's own controls stand in the
 * view's corners, always there: at the top-right `end` (its settings button and the way out),
 * tiles with no surface under them, the model showing through; under it `panel`, its settings,
 * docked at the view's right edge while they are open. The top-left is the file sidebar's, the
 * Preview's sections (Position, Animation), drawn by the frame (`RendererShell.jsx`).
 *
 * @param {{ active: boolean, end?: import("react").ReactNode, panel?: import("react").ReactNode,
 *   children?: import("react").ReactNode }} props
 */
export default function PreviewChrome({ active, end = null, panel = null, children }) {
  return <>
    <div data-preview-chrome="" hidden={active} inert={active}
      className="pointer-events-none absolute inset-0 z-20">
      <ToolbarTooltipScope enabled={!active}>{children}</ToolbarTooltipScope>
    </div>
    {active ? <ToolbarTooltipScope enabled><div data-preview-controls=""
      className="pointer-events-none absolute z-30 flex max-w-[calc(100%-1rem)] flex-col items-end gap-2"
      style={{ top: VIEWPORT_INSET_PX, right: VIEWPORT_INSET_PX, bottom: VIEWPORT_INSET_PX }}>
      {/* The strip's box (padding, a border's room) with no surface: the tiles over the model. */}
      {end ? <div data-preview-corner="" className="pointer-events-auto inline-flex shrink-0 items-center gap-1 rounded-md border border-transparent p-1">
        {end}
      </div> : null}
      {/* `panel`, as tall as its content up to the room under the corner. */}
      {panel ? <div data-preview-panel="" className="pointer-events-none flex min-h-0 max-w-full flex-col">{panel}</div> : null}
    </div></ToolbarTooltipScope> : null}
  </>;
}
