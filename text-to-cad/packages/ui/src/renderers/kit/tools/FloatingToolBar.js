import { Fragment, useLayoutEffect, useRef, useState } from "react";
import { Ellipsis } from "lucide-react";
import {
  DropdownMenu, DropdownMenuCheckboxItem, DropdownMenuContent, DropdownMenuItem, DropdownMenuSub, DropdownMenuSubContent,
  DropdownMenuSubTrigger, DropdownMenuTrigger
} from "@text-to-cad/ui/primitives/dropdown-menu";
import { ToolbarButton } from "@text-to-cad/ui/primitives/toolbar-button";
import { cn } from "@text-to-cad/ui/utils";
import { FLOATING_CHROME_SURFACE_CLASS, FLOATING_SURFACE_CLASS } from "../../../lib/floatingSurface.js";
import { STRIP_BUTTON_CLASS, StripTouchProvider, TOUCH_STRIP_BUTTON_CLASS } from "./stripTouch.js";
import { ChangedDot } from "./ChangedDot.jsx";

export { STRIP_BUTTON_CLASS, StripTouchProvider, TOUCH_STRIP_BUTTON_CLASS, useStripButtonClass, useStripTouch } from "./stripTouch.js";

/**
 * One tool of the strip. The strip draws it; whoever hands it over decides what
 * it is, when it exists and what pressing it does. A tool with settings (Select's filter,
 * Animation's routines) has a small chevron right after its button that opens them (`menu`, a
 * `ToolSettingsMenu` with its "chevron" trigger), as a design tool's toolbar has it.
 *
 * @typedef {object} ViewportTool
 * @property {string} id
 * @property {string} label  The button's accessible name and tooltip.
 * @property {import("react").ReactNode} icon
 * @property {boolean} [active]
 * @property {boolean} [disabled]
 * @property {() => void} onSelect  Every press of the button.
 * @property {string} [description]  `aria-description`.
 * @property {import("react").ReactNode} [menu]  Its modes: the chevron after its button, and the menu it opens.
 * @property {boolean} [changed]  What it sets is off its default (an effect on the model): a dot in its tile's corner.
 */

/**
 * One of the view's controls after the strip's rule (Projection, Display, Preview): its tile as drawn on the
 * strip (`tile`), and what it is as a row of the touch strip's More menu, when there is no room for
 * it: `onSelect` for a press, or `popover` for a control whose tile opens a popover, which then
 * opens from More itself (`anchor`, the More button's ref).
 *
 * @typedef {object} ViewportViewControl
 * @property {string} id
 * @property {string} label
 * @property {import("react").ReactNode} icon
 * @property {boolean} [disabled]
 * @property {boolean} [active]  A control that stays on (a phone's view control): a ticked row in More.
 * @property {import("react").ReactNode} tile
 * @property {() => void} [onSelect]
 * @property {(props: { anchor: import("react").RefObject<HTMLElement>, open: boolean, onOpenChange(open: boolean): void }) => import("react").ReactNode} [popover]
 * @property {(props: { openPopover(): void }) => import("react").ReactNode} [submenu]  In More, its choices as a standard
 *   nested submenu of its row (Projection's, Display's modes); `openPopover` opens its `popover` from More (Display's settings page).
 */

// A plain function, not a component: the strip's own output is the buttons. A tool with a menu is
// its button as every tool's, then the menu's small chevron, a button of its own with its own
// hover, as a design tool's toolbar has it (`ToolSettingsMenu`'s "chevron" trigger).
function toolButton(tool, className = STRIP_BUTTON_CLASS) {
  const active = tool.active === true;
  const button = <ToolbarButton tooltipSide="top" label={tool.label} active={active} disabled={tool.disabled}
    className={cn(className, tool.changed && "relative")} aria-pressed={active} aria-description={tool.description} onClick={() => tool.onSelect()}
    data-changed={tool.changed ? "" : undefined}>
    {tool.icon}
    {tool.changed ? <ChangedDot /> : null}
  </ToolbarButton>;
  if (!tool.menu) return button;
  return <span className="inline-flex items-center" data-tool-split="">{button}{tool.menu}</span>;
}

const GROUP_CLASS = `pointer-events-auto inline-flex min-h-8 max-w-full items-center gap-1 rounded-md p-1 ${FLOATING_CHROME_SURFACE_CLASS}`;
// A More row's icon at a menu item's standard size (16px) and one line weight, whatever drew it
// (a tool's own glyph, a view control's), so the rows read as one list.
const MORE_ICON_CLASS = "flex size-4 shrink-0 items-center justify-center [&_svg]:size-4! [&_:is(svg,path,circle,line,polyline,polygon,rect,ellipse)]:[stroke-width:2px]";
const rule = <span role="separator" aria-orientation="vertical" className="mx-0.5 h-4 w-px shrink-0 bg-border" data-strip-rule="" />;


/**
 * The interaction tools: a dumb strip positioned by the viewport shell. It renders the
 * tools it is handed, left to right, then, after a thin rule, the view's own controls (`views`:
 * a 3D view's Display and Preview), which are no tools: pressing one leaves the tool in hand as it
 * is. It holds no state and knows no tool by name. On a phone (`touch`) it is one row of
 * touch-sized tiles, the tools, with the view's controls (and any tool that does not fit) in a More
 * menu (`TouchStrip`).
 *
 * @param {{ tools: ViewportTool[], views?: ViewportViewControl[], touch?: boolean }} props
 */
export default function FloatingToolBar({ tools = [], views = [], touch = false }) {
  // Nothing to hold, no strip: an empty bar is never drawn.
  if (!tools.length && !views.length) return null;
  if (touch) return <TouchStrip tools={tools} views={views} />;
  return (<div className="relative z-20 flex max-w-full shrink-0 flex-col items-end gap-1" data-cad-toolbar="tools">
      <div role="group" aria-label="Interaction tools" className={cn(GROUP_CLASS, "flex-wrap")}>
        {tools.map(tool => <Fragment key={tool.id}>{toolButton(tool)}</Fragment>)}
        {tools.length && views.length ? rule : null}
        {views.length ? <span className="inline-flex items-center gap-1" data-view-controls="">
          {views.map(view => <Fragment key={view.id}>{view.tile}</Fragment>)}
        </span> : null}
      </div>
  </div>);
}

// The touch strip's geometry, as its classes draw it: 36px tiles 4px apart (`gap-1`), a tool's
// chevron 20px and touching its button, the rule 1px with 2px each side, and 4px of padding inside
// a 1px border.
const TILE_PX = 36, CHEVRON_PX = 20, GAP_PX = 4, RULE_PX = 5, FRAME_PX = 10;

/**
 * How many of the strip's entries (its tools, then its view controls) fit, in order, in `room`
 * pixels: all of them, or as many as leave room for the More button that holds the rest.
 * @param {{ width: number, view: boolean }[]} entries
 */
export function touchStripFit(entries, room, { more = false } = {}) {
  const width = (count, more) => {
    const shown = entries.slice(0, count);
    const items = shown.length + (more ? 1 : 0);
    const ruled = shown.some(entry => !entry.view) && shown.some(entry => entry.view);
    return FRAME_PX + shown.reduce((sum, entry) => sum + entry.width, 0) + (more ? TILE_PX : 0)
      + Math.max(0, items - 1) * GAP_PX + (ruled ? RULE_PX + GAP_PX : 0);
  };
  if (!more && width(entries.length, false) <= room) return entries.length;
  if (more && width(entries.length, true) <= room) return entries.length;
  let count = entries.length - 1;
  while (count > 0 && width(count, true) > room) count -= 1;
  return count;
}

/**
 * A phone's strip: one row of 36px tiles across the view, its tools; the view's controls are always
 * the rows of a More menu (an ellipsis, last on the strip), with any tools that do not fit, from the
 * end, before them. A tool there is a checkbox row, ticked while it is in hand; a view control is
 * its press, or its popover, which then opens from More.
 */
function TouchStrip({ tools, views }) {
  const root = useRef(null);
  const more = useRef(null);
  const [room, setRoom] = useState(Infinity);
  const [openView, setOpenView] = useState(null);
  const pending = useRef(null);
  useLayoutEffect(() => {
    // The room is the column the strip is centred in, which spans the view within its inset.
    const column = root.current?.closest("[data-cad-tool-groups]") || root.current?.parentElement;
    if (!column) return undefined;
    const measure = () => setRoom(column.clientWidth || Infinity);
    measure();
    if (typeof ResizeObserver === "undefined") return undefined;
    const observer = new ResizeObserver(measure);
    observer.observe(column);
    return () => observer.disconnect();
  }, []);
  // The view's controls are always More's rows on a phone, never tiles: the strip keeps to the
  // tools, and what of them does not fit joins the controls in More.
  const toolEntries = tools.map(tool => ({ tool, view: false, width: TILE_PX + (tool.menu ? CHEVRON_PX : 0) }));
  const viewEntries = views.map(view => ({ control: view, view: true, width: TILE_PX }));
  const count = touchStripFit(toolEntries, room, { more: viewEntries.length > 0 });
  const shown = toolEntries.slice(0, count), hidden = [...toolEntries.slice(count), ...viewEntries];
  const shownTools = shown.filter(entry => !entry.view), shownViews = shown.filter(entry => entry.view);
  const overflowViews = hidden.filter(entry => entry.view).map(entry => entry.control);
  const popoverView = overflowViews.find(view => view.id === openView && view.popover);
  // A tool in hand that lives in More: More's button is drawn selected while it is (its row checked).
  const heldInMore = hidden.some(entry => !entry.view && entry.tool.active === true);
  return <StripTouchProvider value={true}>
    <div ref={root} className="relative z-20 flex max-w-full shrink-0 flex-col items-end gap-1" data-cad-toolbar="tools" data-touch-strip="">
      <div role="group" aria-label="Interaction tools" className={cn(GROUP_CLASS, "flex-nowrap")}>
        {shownTools.map(({ tool }) => <Fragment key={tool.id}>{toolButton(tool, TOUCH_STRIP_BUTTON_CLASS)}</Fragment>)}
        {shownTools.length && shownViews.length ? rule : null}
        {shownViews.length ? <span className="inline-flex items-center gap-1" data-view-controls="">
          {shownViews.map(({ control }) => <Fragment key={control.id}>{control.tile}</Fragment>)}
        </span> : null}
        {hidden.length ? <DropdownMenu modal={false}>
          <DropdownMenuTrigger asChild>
            <ToolbarButton ref={more} tooltipSide="top" label="More tools" active={heldInMore} className={TOUCH_STRIP_BUTTON_CLASS} data-strip-more="">
              <Ellipsis aria-hidden="true" />
            </ToolbarButton>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" sideOffset={6} collisionPadding={8} aria-label="More tools"
            className={cn(FLOATING_SURFACE_CLASS, "data-[state=closed]:animate-none!")}
            onCloseAutoFocus={event => {
              // A popover chosen here opens from More once the menu is gone, keeping the focus.
              if (!pending.current) return;
              event.preventDefault();
              setOpenView(pending.current);
              pending.current = null;
            }}>
            {hidden.map(entry => entry.view
              ? entry.control.submenu
                ? <DropdownMenuSub key={entry.control.id}>
                  <DropdownMenuSubTrigger disabled={entry.control.disabled}>
                    <span className={MORE_ICON_CLASS} aria-hidden="true">{entry.control.icon}</span>{entry.control.label}
                  </DropdownMenuSubTrigger>
                  <DropdownMenuSubContent aria-label={entry.control.label} collisionPadding={8} className={cn(FLOATING_SURFACE_CLASS, "data-[state=closed]:animate-none!")}>
                    {entry.control.submenu({ openPopover: () => { pending.current = entry.control.id; } })}
                  </DropdownMenuSubContent>
                </DropdownMenuSub>
              : entry.control.active !== undefined
                ? <DropdownMenuCheckboxItem key={entry.control.id} checked={entry.control.active === true} disabled={entry.control.disabled}
                  onSelect={() => entry.control.onSelect?.()}>
                  <span className={MORE_ICON_CLASS} aria-hidden="true">{entry.control.icon}</span>{entry.control.label}
                </DropdownMenuCheckboxItem>
                : <DropdownMenuItem key={entry.control.id} disabled={entry.control.disabled}
                onSelect={() => { if (entry.control.popover) pending.current = entry.control.id; else entry.control.onSelect?.(); }}>
                <span className={MORE_ICON_CLASS} aria-hidden="true">{entry.control.icon}</span>{entry.control.label}
              </DropdownMenuItem>
              : <DropdownMenuCheckboxItem key={entry.tool.id} checked={entry.tool.active === true} disabled={entry.tool.disabled}
                onSelect={() => entry.tool.onSelect()}>
                <span className={MORE_ICON_CLASS} aria-hidden="true">{entry.tool.icon}</span>{entry.tool.label}
              </DropdownMenuCheckboxItem>)}
          </DropdownMenuContent>
        </DropdownMenu> : null}
        {popoverView ? popoverView.popover({ anchor: more, open: true, onOpenChange: open => { if (!open) setOpenView(null); } }) : null}
      </div>
    </div>
  </StripTouchProvider>;
}
