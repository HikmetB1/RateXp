// The dashboard this app draws: core's dashboard_for_dynatrace.yaml cloned from
// dashboard_base.yaml, bundled as dashboard.json by scripts/sync-dashboard.mjs.
import { getAppId } from "@dynatrace-sdk/app-environment";
import dashboardJson from "./dashboard.json";

export type PanelKind = "number" | "line" | "bar" | "count" | "table";

export interface Panel {
  id: string;
  title: string;
  kind: PanelKind;
  dql: string;
  // Columns the published dashboard hides; this app reads them but draws its own columns.
  hidden_columns?: string[];
}

export interface Dashboard {
  name: string;
  filters: { dql: string; values: Record<string, string> };
  download: { dql: string };
  panels: Panel[];
  // The label groups of core/config.yaml, in order; each is a column of the feedback and
  // download queries, holding the rating's label, its conversation's winning.
  label_groups: string[];
  // For each group that splits its values into when_good and when_bad: each value's side.
  label_sides: Record<string, Record<string, Side>>;
}

export type Side = "good" | "bad";

/** The dashboard showing the records of `environment`: the {environment} in the filter
 * fragment and the dropdowns' values queries filled in. Each panel and the download take
 * the fragment, so they need no filling of their own. */
export function fillEnvironment(dashboard: Dashboard, environment: string): Dashboard {
  const fill = (dql: string) => dql.replace(/\{environment\}/g, () => environment);
  const values = Object.fromEntries(
    Object.entries(dashboard.filters.values).map(([key, dql]) => [key, fill(dql)]),
  );
  return { ...dashboard, filters: { dql: fill(dashboard.filters.dql), values } };
}

// One tenant holds the records of prod and dev. npm run deploy:dev installs the dev copy of
// this app under the app id <id>.dev (scripts/deploy-dev.mjs), and that copy shows dev's.
export const environment = getAppId().endsWith(".dev") ? "dev" : "prod";

export const dashboard = fillEnvironment(dashboardJson as Dashboard, environment);

// The dropdowns, in filters.values order. Type first: skill or session, where a session
// rating is one that has no skill; every other dropdown's values query takes it. Then
// skill, agent, eval and one per label group.
export const FILTER_KEYS = Object.keys(dashboard.filters.values);
export type FilterKey = string;

/** A feedback or download row's labels as {group: value}, in label_groups order: the groups
 * it has a label for. */
export function labelsOf(row: Record<string, unknown>): Record<string, string> {
  return Object.fromEntries(
    dashboard.label_groups.flatMap((group) => (typeof row[group] === "string" ? [[group, row[group]]] : [])),
  );
}

/** A label group's name as a heading: "business_case" -> "Business case". */
export function groupTitle(group: string): string {
  const words = group.replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** The side of `value` in `group`: good (praise) or bad (complaint), or undefined for a
 * group that does not split its values. */
export function labelSide(group: string, value: unknown): Side | undefined {
  return typeof value === "string" ? dashboard.label_sides[group]?.[value] : undefined;
}
