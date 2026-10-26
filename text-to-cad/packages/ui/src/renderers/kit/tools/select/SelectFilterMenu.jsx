import { DropdownMenuLabel, DropdownMenuRadioGroup, DropdownMenuRadioItem, DropdownMenuSeparator } from "@text-to-cad/ui/primitives/dropdown-menu";
import { ToolSettingsMenu } from "../ToolModeMenu.jsx";
import { pickModeOf } from "./selectFilter.js";

/**
 * What a picking tool takes, as a CAD tool's selection priority is: the chevron after its button on
 * the strip, whose dropdown is headed "Pick" and lists the tool's modes (`modes`, `selectFilter.js`)
 * as ONE choice — All first, then each kind alone. Choosing one puts the menu away. Whatever
 * follows (`children`: how a pick grows, Group faces and Group edges) comes after a rule. Measure's
 * menu is this one too (`MeasureFilterMenu.jsx`): `name` marks its trigger and rows
 * (`data-<name>-filter-trigger`, `data-<name>-filter`) and `triggerName` names its chevron
 * ("Measure filter"), so the two chevrons on the strip are told apart. The strip's button shows the
 * mode chosen as a badge on the tool's glyph (`modeGlyphs.jsx`'s `ToolModeIcon`).
 *
 * @param {{ value: readonly string[], onChange(filter: readonly string[]): void,
 *   modes: { id: string, label: string, kinds: readonly string[], icon?: import("react").ReactNode }[],
 *   disabled?: boolean, children?: import("react").ReactNode, name?: string, triggerName?: string }} props
 */
export default function SelectFilterMenu({ value, onChange, modes, disabled = false, children = null, name = "select", triggerName = "Selection filter" }) {
  const mode = pickModeOf(value, modes);
  return <ToolSettingsMenu label="Selection filter"
    triggerLabel={`${triggerName}: ${mode === modes[0] ? "everything" : mode.label}`}
    disabled={disabled} trigger="chevron" triggerProps={{ [`data-${name}-filter-trigger`]: mode === modes[0] ? "all" : mode.id }}>
    <DropdownMenuLabel className="text-tiny font-normal text-muted-foreground">Pick</DropdownMenuLabel>
    <DropdownMenuRadioGroup value={mode.id} onValueChange={id => onChange([...modes.find(candidate => candidate.id === id).kinds])}>
      {modes.map(({ id, label, icon }, index) => <DropdownMenuRadioItem key={id} value={id} {...{ [`data-${name}-filter`]: index === 0 ? "all" : id }}>
        {icon}{label}
      </DropdownMenuRadioItem>)}
    </DropdownMenuRadioGroup>
    {children ? <><DropdownMenuSeparator />{children}</> : null}
  </ToolSettingsMenu>;
}
