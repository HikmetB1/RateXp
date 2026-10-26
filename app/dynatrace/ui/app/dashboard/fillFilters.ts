import { FILTER_KEYS, type FilterKey } from "./loadDashboard";

// null = all. The dashboard's dropdowns are dashboard variables, which matchesValue()
// reads with "*" as "every value"; this app fills the same slots with literals.
export type Filters = Record<FilterKey, string | null>;

export const ALL_FILTERS = Object.fromEntries(FILTER_KEYS.map((key) => [key, null])) as Filters;

// $skill, $agent, ... - each filter's dashboard variable as the fragment names it.
const VARIABLE = new RegExp(`\\$(${FILTER_KEYS.join("|")})\\b`, "g");

/** `value` as a DQL string literal, backslashes and quotes escaped. */
export function dqlString(value: string): string {
  return `"${value.replace(/\\/g, "\\\\").replace(/"/g, '\\"')}"`;
}

/** The panel's DQL with the shared filter fragment in its {filters} slot and each
 * filter's variable ($skill, $language, ...) in the fragment replaced by the picked
 * value, or "*". */
export function fillFilters(dql: string, fragment: string, filters: Filters): string {
  const filled = fragment.replace(VARIABLE, (_, key: FilterKey) =>
    dqlString(filters[key] ?? "*"),
  );
  // A function, so a "$" in a picked value is not read as a replacement pattern.
  return dql.replace("{filters}", () => filled);
}
