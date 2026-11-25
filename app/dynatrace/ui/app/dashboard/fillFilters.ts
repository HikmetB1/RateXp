import { FILTER_KEYS, type FilterKey } from "./loadDashboard";

// null = all. The dashboard's dropdowns are dashboard variables, which matchesValue()
// reads with "*" as "every value"; this app fills the same slots with literals.
export type Filters = Record<FilterKey, string | null>;

export const ALL_FILTERS: Filters = Object.fromEntries(FILTER_KEYS.map((key) => [key, null]));

// $type, $skill, ... - each filter's dashboard variable as the queries name it.
const VARIABLE = new RegExp(`\\$(${FILTER_KEYS.join("|")})\\b`, "g");

/** `value` as a DQL string literal, backslashes and quotes escaped. */
export function dqlString(value: string): string {
  return `"${value.replace(/\\/g, "\\\\").replace(/"/g, '\\"')}"`;
}

/** The DQL with each filter's variable ($type, $language, ...) replaced by the picked
 * value, or "*" - as the published dashboard fills its variables. */
export function fillVariables(dql: string, filters: Filters): string {
  return dql.replace(VARIABLE, (_, key: FilterKey) => dqlString(filters[key] ?? "*"));
}

/** The panel's DQL with the shared filter fragment in its {filters} slot, and every
 * variable in the two filled in. */
export function fillFilters(dql: string, fragment: string, filters: Filters): string {
  // Filled before it goes in, so a "$" in a picked value is never read as a variable, and
  // a function, so it is not read as a replacement pattern either.
  return fillVariables(dql, filters).replace("{filters}", () => fillVariables(fragment, filters));
}

/** The filters with each pick its dropdown no longer lists - the picked type has no
 * ratings for it - back to all; the same object when every pick is listed. */
export function keepListedPicks(filters: Filters, key: FilterKey, listed: string[]): Filters {
  const value = filters[key];
  return value === null || listed.includes(value) ? filters : { ...filters, [key]: null };
}
