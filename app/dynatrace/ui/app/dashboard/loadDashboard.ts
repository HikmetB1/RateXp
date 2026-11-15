// The dashboard this app draws: core's dashboard_for_dynatrace.yaml cloned from
// dashboard_base.yaml, bundled as dashboard.json by scripts/sync-dashboard.mjs.
import { getAppId } from "@dynatrace-sdk/app-environment";
import dashboardJson from "./dashboard.json";

// Type first: skill or session, where a session rating is one that has no skill; every
// other dropdown's values query takes it. The last three are the labels core gives a stored
// conversation; a rating takes its conversation's through the filter fragment's lookup.
export const FILTER_KEYS = ["type", "skill", "agent", "eval", "business_case", "language", "task_type"] as const;
export type FilterKey = (typeof FILTER_KEYS)[number];

export type PanelKind = "number" | "line" | "bar" | "table";

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
  filters: { dql: string; values: Record<FilterKey, string> };
  download: { dql: string };
  panels: Panel[];
}

/** The dashboard showing the records of `environment`: the {environment} in the filter
 * fragment and the dropdowns' values queries filled in. Each panel and the download take
 * the fragment, so they need no filling of their own. */
export function fillEnvironment(dashboard: Dashboard, environment: string): Dashboard {
  const fill = (dql: string) => dql.replace(/\{environment\}/g, () => environment);
  const values = Object.fromEntries(
    Object.entries(dashboard.filters.values).map(([key, dql]) => [key, fill(dql)]),
  ) as Record<FilterKey, string>;
  return { ...dashboard, filters: { dql: fill(dashboard.filters.dql), values } };
}

// One tenant holds the records of prod and dev. npm run deploy:dev installs the dev copy of
// this app under the app id <id>.dev (scripts/deploy-dev.mjs), and that copy shows dev's.
export const environment = getAppId().endsWith(".dev") ? "dev" : "prod";

export const dashboard = fillEnvironment(dashboardJson as Dashboard, environment);
