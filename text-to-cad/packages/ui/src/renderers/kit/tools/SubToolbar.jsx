import { cn } from "@text-to-cad/ui/utils";
import { FLOATING_CHROME_SURFACE_CLASS } from "../../../lib/floatingSurface.js";
import { useStripTouch } from "./stripTouch.js";

// On a phone a row's buttons are the strip's 36px tiles, their icons 18px, and its slider is as tall,
// its thumb big enough to take with a finger.
// A chip in the row (Measure's measurements, `ReferenceChips.jsx`) keeps its own size.
const TOUCH_CLASS = [
  "[&_button:not([data-quick-edit-refs]_*)]:h-9 [&_button:not([data-quick-edit-refs]_*)]:min-w-9 [&_button:not([data-quick-edit-refs]_*)]:rounded-md [&_button:not([data-quick-edit-refs]_*)_svg]:size-4.5!",
  "[&_[data-slot=slider]]:h-9 [&_[data-slot=slider-thumb]]:size-4!"
].join(" ");

/**
 * A tool's own controls while it is in hand: one row hung under the strip, on the strip's surface,
 * its buttons the strip's tiles (24px, or a phone's 36px), its groups — what the tool does, how
 * it looks, what it can undo — parted by a thin rule (`SubToolbarSeparator`), as a design tool's
 * options bar is. It stays up for as long as its tool does.
 *
 * @param {{ label: string, className?: string, children: import("react").ReactNode }} props
 *   `label` names the row for assistive technology ("Drawing controls").
 */
export default function SubToolbar({ label, className, children, ...props }) {
  const touch = useStripTouch();
  return <div role="toolbar" aria-label={label} data-cad-sub-toolbar="" data-touch={touch ? "" : undefined} {...props}
    className={cn("pointer-events-auto inline-flex min-h-8 max-w-full flex-wrap items-center gap-1 rounded-md p-1", FLOATING_CHROME_SURFACE_CLASS, touch && TOUCH_CLASS, className)}>
    {children}
  </div>;
}

// The slider tools' sub-toolbars (the model effects') are one width, 202px, so the column under the
// strip does not change width from one of them to the next. The drawing tools' row is as wide as its
// controls are (colour, stroke width, placement, history).
export const SUB_TOOLBAR_WIDTH_CLASS = "w-[202px]";

/**
 * The width of a slider tool's sub-toolbar: one width for all of
 * them, their slider taking whatever their buttons leave (`min-w-0 flex-1`), so a conditional
 * button (Animation's Routines) shortens the slider rather than the row.
 */
export const SLIDER_SUB_TOOLBAR_CLASS = `${SUB_TOOLBAR_WIDTH_CLASS} flex-nowrap data-[touch]:w-80`;

/**
 * A slider tool's row is one shape: what leads it (Clip's axis; Animation's routines and Play),
 * the slider, its value right beside it, then its actions, Reset last. Its slider is shadcn's, as
 * shadcn draws it (`primitives/slider.jsx`): this only sizes it to the row.
 */
export const SUB_TOOLBAR_SLIDER_CLASS = "h-6 min-w-0 flex-1 px-2";

/** A slider's value, right beside it and only as wide as it reads: the slider takes the rest. */
export function SubToolbarValue({ children, ...props }) {
  return <span className="shrink-0 pr-1 text-tiny tabular-nums text-muted-foreground" {...props}>{children}</span>;
}

/** The thin rule between a sub-toolbar's groups. */
export function SubToolbarSeparator() {
  return <span role="separator" aria-orientation="vertical" className="mx-0.5 h-4 w-px shrink-0 bg-border" data-sub-toolbar-rule="" />;
}
