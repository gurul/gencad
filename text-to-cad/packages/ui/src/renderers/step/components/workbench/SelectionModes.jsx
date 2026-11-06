import { useId } from 'react';
import { Pencil, Ruler } from 'lucide-react';
import { PositionIcon } from '../../../kit/tools/ChangedDot.jsx';
import { CONNECTED_SELECTION, SELECT_GEOMETRY, connectedSelectionApplies } from '../../workbench/selectionFilter.js';
import { DropdownMenuCheckboxItem } from '@text-to-cad/ui/primitives/dropdown-menu';
import SelectFilterMenu from "../../../kit/tools/select/SelectFilterMenu.jsx";

// The two tools that pick in modes share one set of drawings. Each mode has ONE glyph, drawn on
// the 24-unit grid: a cube whole and bold for Parts; faint, with the element a pick takes drawn
// solid, for Faces (its top face filled) and Edges (its front edge heavy), and for how a pick grows,
// Group faces (two joined faces filled) and Group edges (the edges round a face heavy); a dot in a
// ring for Points. The mode menu (the chevron after the tool's button) shows it at full size — All shows the tool's own
// glyph, Select's pointer or Measure's ruler. The strip's button shows the tool's glyph with the mode's glyph shrunk to a
// badge in its top-right corner (none for All); the tool's glyph steps down to the bottom-left to
// make room, and the badge is cut out of it, so the two never touch at the strip's 14px.
// `weight` thickens a glyph's strokes for the badge, which is drawn at under half size.
const TOOL_GLYPHS = Object.freeze({
  select: <path d="M4.037 4.688a.495.495 0 0 1 .651-.651l16 6.5a.5.5 0 0 1-.063.947l-6.124 1.58a2 2 0 0 0-1.438 1.435l-1.579 6.126a.5.5 0 0 1-.947.063z" />,
  measure: <>
    <path d="M21.3 15.3a2.4 2.4 0 0 1 0 3.4l-2.6 2.6a2.4 2.4 0 0 1-3.4 0L2.7 8.7a2.41 2.41 0 0 1 0-3.4l2.6-2.6a2.41 2.41 0 0 1 3.4 0Z" />
    <path d="m14.5 12.5 2-2" /><path d="m11.5 9.5 2-2" /><path d="m8.5 6.5 2-2" /><path d="m17.5 15.5 2-2" />
  </>,
});
const CUBE = 'M12 2.5 20.5 7.25v9.5L12 21.5l-8.5-4.75v-9.5Z';
const CUBE_SEAMS = 'M3.5 7.25 12 12l8.5-4.75M12 12v9.5';
const faintCube = weight => <g strokeWidth={1.5 * weight} strokeOpacity="0.45"><path d={CUBE} /><path d={CUBE_SEAMS} /></g>;
const MODE_GLYPHS = Object.freeze({
  parts: weight => <g strokeWidth={2 * weight}><path d={CUBE} /><path d={CUBE_SEAMS} /></g>,
  faces: weight => <>{faintCube(weight)}<path d="M12 2.5 20.5 7.25 12 12 3.5 7.25Z" fill="currentColor" strokeWidth={2 * weight} /></>,
  edges: weight => <>{faintCube(weight)}<path d="M12 12v9.5" strokeWidth={3.5 * weight} /></>,
  // How a pick grows: Group faces, two smoothly joined faces (the top and the left) taken together;
  // Group edges, the chain of edges around a face, heavy all the way round.
  groupFaces: weight => <>{faintCube(weight)}<path d="M12 2.5 20.5 7.25 12 12 3.5 7.25Z M3.5 7.25 12 12v9.5l-8.5-4.75Z" fill="currentColor" strokeWidth={2 * weight} /></>,
  groupEdges: weight => <>{faintCube(weight)}<path d="M12 2.5 20.5 7.25 12 12 3.5 7.25Z" strokeWidth={3 * weight} /></>,
  points: weight => <><circle cx="12" cy="12" r="8.5" strokeWidth={1.5 * weight} strokeOpacity="0.45" /><circle cx="12" cy="12" r="4" fill="currentColor" stroke="none" /></>,
});
const SVG = { viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round", strokeLinejoin: "round" };
// Where the badge sits: the mode's glyph at 0.44 of its size, centred on (18.5, 5.5).
const BADGE_SCALE = 0.44, BADGE_CENTRE = [18.5, 5.5];
const BADGE_TRANSFORM = `translate(${BADGE_CENTRE[0] - 12 * BADGE_SCALE} ${BADGE_CENTRE[1] - 12 * BADGE_SCALE}) scale(${BADGE_SCALE})`;

/** A mode's own glyph at full size, for the mode menu off the strip's chevron: `mode` "all" is the tool's glyph (`tool`). */
function ModeGlyph({ tool, mode, ...props }) {
  const glyph = MODE_GLYPHS[mode];
  return <svg {...SVG} data-mode-glyph={glyph ? mode : tool} {...props}>{glyph ? glyph(1) : TOOL_GLYPHS[tool]}</svg>;
}

/** The strip's composite: the tool's glyph (`tool`, "select" or "measure") badged with `mode`'s glyph, none for "all". */
function ToolModeIcon({ tool, mode, ...props }) {
  const mask = `tool-mode-${useId().replace(/[^\w-]/g, '')}`;
  const glyph = MODE_GLYPHS[mode];
  return <svg {...SVG} data-tool-icon-base={tool} {...props}>
    {glyph ? <>
      <mask id={mask}><rect width="24" height="24" fill="white" /><circle cx={BADGE_CENTRE[0]} cy={BADGE_CENTRE[1]} r="6.25" fill="black" /></mask>
      <g mask={`url(#${mask})`}><g transform="translate(0 4) scale(0.84)" strokeWidth="2.3">{TOOL_GLYPHS[tool]}</g></g>
      <g data-tool-icon-badge={mode} transform={BADGE_TRANSFORM}>{glyph(1.7)}</g>
    </> : TOOL_GLYPHS[tool]}
  </svg>;
}

/** The Select tool's button icon: the pointer, whatever it is filtered to pick. */
export function SelectIcon(props) {
  return <ToolModeIcon tool="select" mode="all" {...props} />;
}

/** The Measure tool's button icon: the ruler (it measures between points, with no snapping mode). */
export function MeasureIcon(props) {
  return <ToolModeIcon tool="measure" mode="all" {...props} />;
}

const glyphIcon = mode => <ModeGlyph tool="select" mode={mode} className="size-3.5" aria-hidden="true" />;
const lucideIcon = Icon => <Icon className="size-3.5" strokeWidth={2} aria-hidden="true" />;
// What else Select picks, beside the model's geometry: Position's knobs (where the file has joints
// to move), the annotations and measurements.
const SELECT_OVERLAYS = Object.freeze([
  { id: 'position', label: 'Position', icon: lucideIcon(PositionIcon) },
  { id: 'annotation', label: 'Annotations', icon: lucideIcon(Pencil) },
  { id: 'measurement', label: 'Measurement', icon: lucideIcon(Ruler) },
]);
// Each connected-selection option's glyph.
const GROUP_GLYPHS = Object.freeze({ tangentFaces: 'groupFaces', edgeChain: 'groupEdges' });
/** Every kind a STEP's Select can pick, ticked when a file opens: Parts too, which a part file's filter does not offer. */
export const STEP_SELECT_DEFAULT = Object.freeze([...SELECT_GEOMETRY, ...SELECT_OVERLAYS].map(kind => kind.id));

/**
 * A STEP's selection filter (`kit/tools/select/SelectFilterMenu.jsx`): Parts (only in an
 * assembly), Faces, Edges, Position (where the file has joints), Annotations and Measurement, each on
 * its own; then the connected-selection options that do something under it — Group faces while
 * Faces is ticked, Group edges while Edges is. An option that does nothing is not shown, and keeps
 * its choice for when it does.
 *
 * @param {{ value: readonly string[], onChange(filter: readonly string[]): void, assembly: boolean, posable: boolean,
 *   connected: { edgeChain: boolean, tangentFaces: boolean },
 *   onConnectedChange(id: "edgeChain" | "tangentFaces", checked: boolean): void, disabled?: boolean }} props
 */
export function SelectModeMenu({ value, onChange, assembly, posable, connected, onConnectedChange, disabled = false }) {
  const kinds = [
    ...SELECT_GEOMETRY.filter(item => assembly || !item.assemblyOnly).map(item => ({ id: item.id, label: item.label, icon: glyphIcon(item.id) })),
    ...SELECT_OVERLAYS.filter(kind => posable || kind.id !== 'position'),
  ];
  const options = CONNECTED_SELECTION.filter(option => connectedSelectionApplies(option.id, value));
  return <SelectFilterMenu value={value} onChange={onChange} kinds={kinds} disabled={disabled}>
    {options.length ? options.map(option => <DropdownMenuCheckboxItem key={option.id} checked={connected[option.id] === true}
      onSelect={event => event.preventDefault()} onCheckedChange={checked => onConnectedChange(option.id, checked === true)}>
      {glyphIcon(GROUP_GLYPHS[option.id])}{option.label}
    </DropdownMenuCheckboxItem>) : null}
  </SelectFilterMenu>;
}
