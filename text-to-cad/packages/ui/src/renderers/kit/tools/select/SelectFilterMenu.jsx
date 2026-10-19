import { DropdownMenuCheckboxItem, DropdownMenuLabel, DropdownMenuSeparator } from "@text-to-cad/ui/primitives/dropdown-menu";
import { ToolSettingsMenu } from "../ToolModeMenu.jsx";
import { toggleSelectAll, toggleSelectFilter } from "./selectFilter.js";

/**
 * Select's selection filter, as a CAD tool's is: the chevron after Select's button on the strip,
 * whose dropdown is headed "Selection filter" and lists a checkbox per kind of thing Select picks
 * (`kinds`, each on its own), under Select all — ticked when every kind is, a dash when some are,
 * and pressing it ticks them all (or, with all ticked, none). Ticking leaves the menu open, so
 * several can be changed in one go. Whatever follows (`children`: how a pick grows, Group faces and
 * Group edges) comes after a rule.
 *
 * @param {{ value: readonly string[], onChange(filter: readonly string[]): void,
 *   kinds: { id: string, label: string, icon?: import("react").ReactNode }[],
 *   disabled?: boolean, children?: import("react").ReactNode }} props
 */
export default function SelectFilterMenu({ value, onChange, kinds, disabled = false, children = null }) {
  const ids = kinds.map(kind => kind.id);
  const ticked = kinds.filter(kind => value.includes(kind.id));
  const all = ticked.length === kinds.length, some = ticked.length > 0;
  return <ToolSettingsMenu label="Selection filter"
    triggerLabel={`Selection filter: ${all ? "everything" : some ? ticked.map(kind => kind.label).join(", ") : "nothing"}`}
    disabled={disabled} trigger="chevron" triggerProps={{ "data-select-filter-trigger": all ? "all" : value.join(" ") }}>
    <DropdownMenuLabel className="text-tiny font-normal text-muted-foreground">Selection filter</DropdownMenuLabel>
    <DropdownMenuCheckboxItem checked={all ? true : some ? "indeterminate" : false} data-select-filter="all"
      onSelect={event => event.preventDefault()} onCheckedChange={() => onChange(toggleSelectAll(value, ids))}>
      Select all
    </DropdownMenuCheckboxItem>
    <DropdownMenuSeparator />
    {kinds.map(({ id, label, icon }) => <DropdownMenuCheckboxItem key={id} checked={value.includes(id)} data-select-filter={id}
      onSelect={event => event.preventDefault()} onCheckedChange={checked => onChange(toggleSelectFilter(value, id, checked === true))}>
      {icon}{label}
    </DropdownMenuCheckboxItem>)}
    {children ? <><DropdownMenuSeparator />{children}</> : null}
  </ToolSettingsMenu>;
}
