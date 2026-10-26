// The dashboard this app draws: core's dashboard_for_dynatrace.yaml cloned from
// dashboard_base.yaml, bundled as dashboard.json by scripts/sync-dashboard.mjs.
import dashboardJson from "./dashboard.json";

// The last three are the labels core gives a stored conversation; a rating takes its
// conversation's through the filter fragment's lookup.
export const FILTER_KEYS = ["skill", "agent", "eval", "business_case", "language", "task_type"] as const;
export type FilterKey = (typeof FILTER_KEYS)[number];

export type PanelKind = "number" | "line" | "bar" | "table";

export interface Panel {
  id: string;
  title: string;
  kind: PanelKind;
  dql: string;
  max_result_megabytes?: number;
}

export interface Dashboard {
  name: string;
  filters: { dql: string; values: Record<FilterKey, string> };
  download: { dql: string };
  panels: Panel[];
}

export const dashboard = dashboardJson as Dashboard;
