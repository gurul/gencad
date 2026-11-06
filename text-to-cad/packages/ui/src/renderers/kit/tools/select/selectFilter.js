// What Select picks, as the person filters it from the dropdown on its chevron
// (`SelectFilterMenu.jsx`), as a CAD tool's selection filter is: a checkbox per kind of thing it
// can pick, each on its own, all ticked when a file opens, and Select all above
// them. A filter is the list of ticked ids.
//
// Importing this module has no environmental effects.

/** The filter after `id` is ticked (`checked`) or unticked. */
export function toggleSelectFilter(filter, id, checked) {
  const rest = filter.filter(item => item !== id);
  return checked ? [...rest, id] : rest;
}

/** Select all: every kind ticked; pressed with every kind ticked already, none. */
export function toggleSelectAll(filter, ids) {
  return ids.every(id => filter.includes(id)) ? [] : [...ids];
}

/** Whether `filter` picks `id`'s kind. */
export const selects = (filter, id) => filter.includes(id);
