import { useEffect, useRef } from 'react';
import { Circle, Eraser, MoveUpRight, Pencil, Redo2, Slash, Square, Trash2, Type, Undo2 } from 'lucide-react';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuRadioGroup, DropdownMenuRadioItem, DropdownMenuSeparator,
  DropdownMenuSub, DropdownMenuSubContent, DropdownMenuSubTrigger, DropdownMenuTrigger
} from '@text-to-cad/ui/primitives/dropdown-menu';
import { ToolbarButton } from '@text-to-cad/ui/primitives/toolbar-button';
import { cn } from '@text-to-cad/ui/utils';
import { FLOATING_SURFACE_CLASS } from '../lib/floatingSurface.js';
import SubToolbar, { SUB_TOOLBAR_WIDTH_CLASS } from '../renderers/kit/tools/SubToolbar.jsx';
import { ToolSettingsMenu } from '../renderers/kit/tools/ToolModeMenu.jsx';

/**
 * Annotate's sub-toolbar (`AnnotationToolbar`): its tools — the pen, each shape, the eraser — the colour,
 * weight and line style of what is drawn next and where it is drawn (on the model or in space), and
 * its history and Clear, all the annotation session's (`session.js`). The same colour, weight and line
 * style dropdowns (`AnnotationStylePickers`) restyle the ink Select has picked, on its selection's bar.
 */

/**
 * The annotation editor's tools a host offers. Its lock, image, frame, embed and laser tools are left out.
 * @typedef {'freedraw' | 'line' | 'arrow' | 'rectangle' | 'ellipse' | 'text' | 'eraser'} AnnotationTool
 */
/** @typedef {{ id: AnnotationTool, label: string, Icon: typeof Pencil }} AnnotationToolEntry */
// The pen, what Annotate opens on, and the eraser.
const PEN = { id: 'freedraw', label: 'Pen', Icon: Pencil };
const ERASER = { id: 'eraser', label: 'Eraser', Icon: Eraser };
// The shapes, the line first; text with them, a mark put down in place.
/** @type {readonly AnnotationToolEntry[]} */
export const ANNOTATION_SHAPE_TOOLS = [
  { id: 'line', label: 'Line', Icon: Slash },
  { id: 'arrow', label: 'Arrow', Icon: MoveUpRight },
  { id: 'rectangle', label: 'Rectangle', Icon: Square },
  { id: 'ellipse', label: 'Ellipse', Icon: Circle },
  { id: 'text', label: 'Text', Icon: Type },
];
/** @type {readonly AnnotationToolEntry[]} */
const ANNOTATION_TOOL_ENTRIES = [PEN, ...ANNOTATION_SHAPE_TOOLS, ERASER];
/** @type {readonly AnnotationTool[]} */
export const ANNOTATION_TOOLS = ANNOTATION_TOOL_ENTRIES.map(tool => tool.id);
/** The icon of an annotation tool (the pen's for one it does not know): the strip's Annotate shows the tool in hand. */
export const annotationToolIcon = id => (ANNOTATION_TOOL_ENTRIES.find(tool => tool.id === id) || PEN).Icon;

// Saturated enough to stand out from a shaded model in either theme; black and
// white for the cases a neon cannot cover (a white page, a dark render).
/** @type {readonly { value: string, label: string }[]} */
export const ANNOTATION_COLORS = [
  { value: '#ff2d55', label: 'Neon red' },
  { value: '#ff7a00', label: 'Neon orange' },
  { value: '#ffe600', label: 'Neon yellow' },
  { value: '#39ff14', label: 'Neon green' },
  { value: '#00e5ff', label: 'Neon cyan' },
  { value: '#2979ff', label: 'Electric blue' },
  { value: '#d500f9', label: 'Neon magenta' },
  { value: '#ffffff', label: 'White' },
  { value: '#111111', label: 'Black' },
];
export const DEFAULT_OVERLAY_ANNOTATION_COLOR = ANNOTATION_COLORS[0].value;
const WHITE = '#ffffff', BLACK = '#111111';
/**
 * The colours offered under `colorScheme`: the neons, and one neutral that reads against the
 * viewer — white in dark mode, near-black in light mode, where white would vanish into the page.
 * @param {'light' | 'dark'} colorScheme
 */
export function annotationColors(colorScheme) {
  const neutral = colorScheme === 'dark' ? WHITE : BLACK;
  return ANNOTATION_COLORS.filter(option => option.value !== (neutral === WHITE ? BLACK : WHITE));
}

// A shape's stroke in px; the pen draws a little heavier at the same weight (`geometry.js`).
/** @type {readonly { value: number, label: string }[]} */
export const ANNOTATION_STROKE_WIDTHS = [
  { value: 1, label: 'Thin' },
  { value: 2, label: 'Medium' },
  { value: 4, label: 'Bold' },
];
/** @typedef {'solid' | 'dashed' | 'dotted'} AnnotationStrokeStyle */
// How a shape's line is stroked; the pen's freehand ink is always solid.
/** @type {readonly { value: AnnotationStrokeStyle, label: string }[]} */
export const ANNOTATION_STROKE_STYLES = [
  { value: 'solid', label: 'Solid' },
  { value: 'dashed', label: 'Dashed' },
  { value: 'dotted', label: 'Dotted' },
];
// Where ink lies, as its glyph: a sphere, in three dimensions, for ink drawn on the model's surface;
// a flat sheet seen in perspective, a CAD tool's plane, for ink drawn on a plane.
const GLYPH = { viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeLinecap: 'round', strokeLinejoin: 'round' };
function SurfaceGlyph({ strokeWidth = 2, ...props }) {
  return <svg {...GLYPH} strokeWidth={strokeWidth} {...props}>
    <circle cx="12" cy="12" r="9" />
    <ellipse cx="12" cy="12" rx="9" ry="3.5" />
    <ellipse cx="12" cy="12" rx="3.5" ry="9" />
  </svg>;
}
function PlaneGlyph({ strokeWidth = 2, ...props }) {
  return <svg {...GLYPH} strokeWidth={strokeWidth} {...props}>
    <path d="M7.5 6.5h14l-5 11h-14Z" />
    <path d="M14.5 6.5l-5 11M5 12h14" strokeWidth={1.25} strokeOpacity="0.5" />
  </svg>;
}
/** @typedef {'surface' | 'space'} AnnotationPlacement */
// Where ink lies: on the model under it (carried with its part), or in space, on a plane facing the
// view through the orbit point, on no part. Only what is drawn next: ink already down stays put.
/** @type {readonly { value: AnnotationPlacement, label: string, Icon: typeof Pencil }[]} */
export const ANNOTATION_PLACEMENTS = [
  { value: 'surface', label: 'Draw on surface', Icon: SurfaceGlyph },
  { value: 'space', label: 'Draw on plane', Icon: PlaneGlyph },
];
const placementGlyph = placement => {
  const { Icon } = ANNOTATION_PLACEMENTS.find(option => option.value === placement) ?? ANNOTATION_PLACEMENTS[0];
  return <Icon className="size-3" strokeWidth={2} aria-hidden="true" />;
};
// The style as a 2px line across a button, on the diagonal, dashed or dotted as it draws.
const STYLE_DASHES = Object.freeze({ solid: undefined, dashed: '4 2.5', dotted: '0.01 3.5' });
const styleGlyph = style => <svg aria-hidden="true" viewBox="0 0 12 12" className="size-3" fill="none" stroke="currentColor"
  strokeWidth="2" strokeLinecap="round"><path d="M2 10L10 2" strokeDasharray={STYLE_DASHES[style]} /></svg>;
// The weight as a dot, 3px, 5px or 7px across, whatever it draws on the model: a dot, so it never
// reads as a line style.
const strokeGlyph = width => {
  const size = width === 1 ? 3 : width === 2 ? 5 : 7;
  return <span aria-hidden="true" className="block rounded-full bg-current" style={{ width: `${size}px`, height: `${size}px` }} />;
};
const swatch = color => ({ backgroundColor: color, boxShadow: 'inset 0 0 0 1px color-mix(in oklab, currentColor 35%, transparent)' });
const ROW = 'flex min-w-0 flex-wrap items-center gap-0.5';

/**
 * One of a mark's styles as a dropdown: its button shows the value (no chevron), and opens a menu
 * of the choices — each its glyph and its name, or, where the glyph says it all (`glyphsOnly`: a
 * weight, a line style), a row of the glyphs alone, the current one marked, each keeping its name
 * for assistive technology. One chosen closes it.
 */
function StyleMenu({ label, options, value, glyph, onChange, disabled, glyphsOnly = false }) {
  return <DropdownMenu modal={false}>
    <DropdownMenuTrigger asChild>
      <ToolbarButton tooltip={false} label={label} disabled={disabled}>{glyph(value)}</ToolbarButton>
    </DropdownMenuTrigger>
    <DropdownMenuContent align="start" sideOffset={4} collisionPadding={8} aria-label={label}
      className={cn(FLOATING_SURFACE_CLASS, glyphsOnly ? 'w-auto min-w-0 p-1.5' : 'w-40', 'data-[state=closed]:animate-none!')}>
      {glyphsOnly ? <div className="flex gap-1">
        {options.map(option => <DropdownMenuItem key={option.value} aria-label={option.label} data-style-option={option.value}
          data-checked={String(option.value) === String(value) ? '' : undefined} onSelect={() => onChange(option.value)}
          className="size-7 justify-center rounded-md p-0 data-[checked]:bg-accent">{glyph(option.value)}</DropdownMenuItem>)}
      </div> : <DropdownMenuRadioGroup value={String(value)} onValueChange={next => onChange(options.find(option => String(option.value) === next).value)}>
        {options.map(option => <DropdownMenuRadioItem key={option.value} value={String(option.value)} aria-label={option.label}>
          <span className="grid size-3.5 place-items-center">{glyph(option.value)}</span>{option.label}
        </DropdownMenuRadioItem>)}
      </DropdownMenuRadioGroup>}
    </DropdownMenuContent>
  </DropdownMenu>;
}
const colorGlyph = color => <span className="size-3 rounded-full" style={swatch(color)} aria-hidden="true" />;
// The colour wheel's swatch: every hue round the circle.
const WHEEL = { background: 'conic-gradient(#ff2d55, #ffe600, #39ff14, #00e5ff, #2979ff, #d500f9, #ff2d55)' };

/**
 * The colour: its button shows the colour in hand, and opens a grid of swatches, unnamed (each
 * keeps its name for assistive technology) — the palette, then the colour wheel, which opens the
 * system's colour picker for any other colour, kept once the picker closes (one change, one step
 * of the history, however long it is dragged). A colour off the palette shows on the button as it
 * is, and no swatch is marked.
 */
function ColorMenu({ value, colors, onChange, disabled }) {
  const picker = useRef(null);
  const commit = useRef(onChange);
  commit.current = onChange;
  // The picker's colour is taken as it closes (`change`), not as it is dragged (`input`).
  useEffect(() => {
    const input = picker.current;
    if (!input) return undefined;
    const changed = () => commit.current(input.value);
    input.addEventListener('change', changed);
    return () => input.removeEventListener('change', changed);
  }, []);
  const pick = () => {
    const input = picker.current;
    if (!input) return;
    try { input.showPicker(); } catch { input.click(); }
  };
  return <>
    <DropdownMenu modal={false}>
      <DropdownMenuTrigger asChild>
        <ToolbarButton tooltip={false} label="Color" disabled={disabled}>{colorGlyph(value)}</ToolbarButton>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" sideOffset={4} collisionPadding={8} aria-label="Color"
        className={cn(FLOATING_SURFACE_CLASS, 'w-auto min-w-0 p-1.5 data-[state=closed]:animate-none!')}>
        <div className="grid grid-cols-3 gap-1">
          {colors.map(option => <DropdownMenuItem key={option.value} aria-label={option.label} data-color={option.value}
            data-checked={option.value === value ? '' : undefined} onSelect={() => onChange(option.value)}
            className="size-7 justify-center rounded-md p-0 data-[checked]:bg-accent">
            <span className="size-4 rounded-full" style={swatch(option.value)} aria-hidden="true" />
          </DropdownMenuItem>)}
          <DropdownMenuItem aria-label="Custom color" data-color="custom" onSelect={pick} className="size-7 justify-center rounded-md p-0">
            <span className="size-4 rounded-full" style={WHEEL} aria-hidden="true" />
          </DropdownMenuItem>
        </div>
      </DropdownMenuContent>
    </DropdownMenu>
    <input ref={picker} type="color" value={/^#[0-9a-f]{6}$/i.test(value) ? value : '#ff2d55'} onChange={() => {}}
      tabIndex={-1} aria-hidden="true" className="pointer-events-none absolute size-0 opacity-0" data-color-picker="" />
  </>;
}

/**
 * The colour, weight and line style dropdowns (`StyleMenu`) — the ink picked, on its selection's bar. Each is left out where it has nothing to set (`width`/`dash`
 * null: no stroke picked); `placement` only where Annotate puts ink down. `children` follow them on
 * their row.
 *
 * @param {{ color: string, width?: number | null, dash?: AnnotationStrokeStyle | null, placement?: AnnotationPlacement | null,
 *   onColor(value: string): void, onWidth?(value: number): void, onDash?(value: AnnotationStrokeStyle): void,
 *   onPlacement?(value: AnnotationPlacement): void, colors?: readonly { value: string, label: string }[],
 *   disabled?: boolean, label: string, className?: string,
 *   children?: import('react').ReactNode }} props
 */
export function AnnotationStylePickers({ color, width = null, dash = null, placement = null, onColor, onWidth, onDash, onPlacement,
  colors = ANNOTATION_COLORS, disabled = false, label, className = ROW, children = null }) {
  return <div role="group" aria-label={label} className={className}>
    <ColorMenu value={color.toLowerCase()} colors={colors} onChange={onColor} disabled={disabled} />
    {width == null ? null : <StyleMenu label="Stroke width" options={ANNOTATION_STROKE_WIDTHS} value={width} glyph={strokeGlyph}
      onChange={value => onWidth?.(value)} disabled={disabled} glyphsOnly />}
    {dash == null ? null : <StyleMenu label="Line style" options={ANNOTATION_STROKE_STYLES} value={dash} glyph={styleGlyph}
      onChange={value => onDash?.(value)} disabled={disabled} glyphsOnly />}
    {placement == null ? null : <StyleMenu label="Placement" options={ANNOTATION_PLACEMENTS} value={placement} glyph={placementGlyph}
      onChange={value => onPlacement?.(value)} disabled={disabled} />}
    {children}
  </div>;
}

const icon = Icon => <Icon className="size-3" strokeWidth={2} aria-hidden="true" />;

/**
 * Annotate's sub-toolbar (`kit/tools/SubToolbar.jsx`), one row under the strip while Annotate is the tool:
 * its tools, every one a button — the pen, the line, the arrow, the rectangle, the ellipse, text,
 * the eraser; then what is drawn next — its colour (`annotationColors`, for the viewer's
 * `colorScheme`, or any from the wheel), weight, line style and placement, each a dropdown — and
 * Undo, Redo (the annotation's history, `history`) and Clear, with no rule between them. In a view
 * too narrow for the row, the seven tools and the seven after them are two rows.
 * A flat view, where ink has nowhere to lie but the sheet, has no placement to choose (`placements={false}`).
 * @param {{ annotation: import('./session.js').AnnotationSession, colorScheme?: 'light' | 'dark', placements?: boolean,
 *   history: { canUndo: boolean, canRedo: boolean, undo(): void, redo(): void } }} props
 */
export function AnnotationToolbar({ annotation, history, colorScheme = 'light', placements = true }) {
  const disabled = !annotation.ready;
  const toolButton = ({ id, label, Icon }) => <ToolbarButton key={id} tooltip={false} label={label} disabled={disabled}
    active={!disabled && annotation.tool === id} aria-pressed={!disabled && annotation.tool === id} onClick={() => annotation.selectTool(id)}>
    {icon(Icon)}
  </ToolbarButton>;
  // Seven tools, then seven settings and actions: two rows of seven, one over the other, their
  // buttons column for column — the sub-toolbars' one width (`SUB_TOOLBAR_WIDTH_CLASS`), whatever
  // the view's.
  return <SubToolbar label="Annotation controls" data-annotation-controls=""
    className={cn("text-to-cad-annotation-toolbar flex-col flex-nowrap items-stretch", SUB_TOOLBAR_WIDTH_CLASS)}>
    <div role="group" aria-label="Annotation tools" className="flex items-center gap-1">{[PEN, ...ANNOTATION_SHAPE_TOOLS, ERASER].map(toolButton)}</div>

    <div className="flex items-center gap-1">
      <AnnotationStylePickers label="Annotation style" className="contents" disabled={disabled} colors={annotationColors(colorScheme)}
        color={annotation.color} width={annotation.strokeWidth ?? 2} dash={annotation.strokeStyle ?? 'solid'} placement={placements ? annotation.placement ?? 'surface' : null}
        onColor={annotation.selectColor} onWidth={annotation.selectStrokeWidth} onDash={annotation.selectStrokeStyle} onPlacement={annotation.selectPlacement} />
      <div role="group" aria-label="Annotation history" className="contents">
        <ToolbarButton tooltip={false} label="Undo" disabled={disabled || !history.canUndo} onClick={() => history.undo()}>{icon(Undo2)}</ToolbarButton>
        <ToolbarButton tooltip={false} label="Redo" disabled={disabled || !history.canRedo} onClick={() => history.redo()}>{icon(Redo2)}</ToolbarButton>
        <ToolbarButton tooltip={false} label="Clear annotations" disabled={disabled || !annotation.hasContent} onClick={() => annotation.clear()}>{icon(Trash2)}</ToolbarButton>
      </div>
    </div>
  </SubToolbar>;
}

const swatchGlyph = color => <span aria-hidden="true" className="block size-3.5 rounded-full shadow-[inset_0_0_0_1px_color-mix(in_oklab,currentColor_35%,transparent)]" style={{ backgroundColor: color }} />;
const keepOpen = event => event.preventDefault();

/**
 * Annotate on a phone, where its sub-toolbar would cover the model: the chevron after its tile on the
 * strip, as Select's filter is, and the menu it opens — the tools (choosing one takes Annotate up,
 * `onTakeUp`), then what is drawn next, its Colour, Stroke width, Line style and Placement each a
 * submenu, then Undo, Redo and Clear annotations. A choice of style or history keeps the menu open.
 * A flat view has no Placement (`placements={false}`).
 * @param {{ annotation: import('./session.js').AnnotationSession, colorScheme?: 'light' | 'dark', onTakeUp?: () => void,
 *   placements?: boolean, history: { canUndo: boolean, canRedo: boolean, undo(): void, redo(): void } }} props
 */
export function AnnotationMenu({ annotation, history, colorScheme = 'light', onTakeUp, placements = true }) {
  const ready = annotation.ready;
  const sub = (label, options, value, glyph, onChange) => <DropdownMenuSub>
    <DropdownMenuSubTrigger className="gap-2">{glyph(value)}{label}</DropdownMenuSubTrigger>
    <DropdownMenuSubContent aria-label={label} className={cn(FLOATING_SURFACE_CLASS, 'w-44')}>
      <DropdownMenuRadioGroup value={String(value)} onValueChange={next => onChange(options.find(option => String(option.value) === next).value)}>
        {options.map(option => <DropdownMenuRadioItem key={option.value} value={String(option.value)} onSelect={keepOpen}>
          {glyph(option.value)}{option.label}
        </DropdownMenuRadioItem>)}
      </DropdownMenuRadioGroup>
    </DropdownMenuSubContent>
  </DropdownMenuSub>;
  const colors = annotationColors(colorScheme);
  return <ToolSettingsMenu label="Annotation" triggerLabel="Annotation settings" trigger="chevron">
    <DropdownMenuRadioGroup value={annotation.tool} onValueChange={id => { annotation.selectTool(id); onTakeUp?.(); }} aria-label="Annotation tools">
      {ANNOTATION_TOOL_ENTRIES.map(({ id, label, Icon }) => <DropdownMenuRadioItem key={id} value={id}>{icon(Icon)}{label}</DropdownMenuRadioItem>)}
    </DropdownMenuRadioGroup>
    <DropdownMenuSeparator />
    {sub('Color', colors, String(annotation.color).toLowerCase(), swatchGlyph, annotation.selectColor)}
    {sub('Stroke width', ANNOTATION_STROKE_WIDTHS, annotation.strokeWidth ?? 2, strokeGlyph, annotation.selectStrokeWidth)}
    {sub('Line style', ANNOTATION_STROKE_STYLES, annotation.strokeStyle ?? 'solid', styleGlyph, annotation.selectStrokeStyle)}
    {placements ? sub('Placement', ANNOTATION_PLACEMENTS, annotation.placement ?? 'surface', placementGlyph, annotation.selectPlacement) : null}
    <DropdownMenuSeparator />
    <DropdownMenuItem disabled={!ready || !history.canUndo} onSelect={event => { keepOpen(event); history.undo(); }}>{icon(Undo2)}Undo</DropdownMenuItem>
    <DropdownMenuItem disabled={!ready || !history.canRedo} onSelect={event => { keepOpen(event); history.redo(); }}>{icon(Redo2)}Redo</DropdownMenuItem>
    <DropdownMenuItem disabled={!ready || !annotation.hasContent} onSelect={() => annotation.clear()}>{icon(Trash2)}Clear annotations</DropdownMenuItem>
  </ToolSettingsMenu>;
}
