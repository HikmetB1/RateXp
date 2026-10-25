import type { FilterKey } from "./loadDashboard";

// null = all. The dashboard's dropdowns are dashboard variables, which matchesValue()
// reads with "*" as "every value"; this app fills the same slots with literals.
export type Filters = Record<FilterKey, string | null>;

export const ALL_FILTERS: Filters = { skill: null, agent: null, eval: null };

/** `value` as a DQL string literal, backslashes and quotes escaped. */
export function dqlString(value: string): string {
  return `"${value.replace(/\\/g, "\\\\").replace(/"/g, '\\"')}"`;
}

/** The panel's DQL with the shared filter fragment in its {filters} slot and each
 * $skill / $agent / $eval in the fragment replaced by the picked value, or "*". */
export function fillFilters(dql: string, fragment: string, filters: Filters): string {
  const filled = fragment.replace(/\$(skill|agent|eval)\b/g, (_, key: FilterKey) =>
    dqlString(filters[key] ?? "*"),
  );
  // A function, so a "$" in a picked value is not read as a replacement pattern.
  return dql.replace("{filters}", () => filled);
}
