// Clone core's dashboard_base.yaml into the Dynatrace dashboard, as
// core/modules/dashboard/clone_dashboard_from_base.py does, and write it to
// ui/app/dashboard/dashboard.json - the file the app bundles, since an AppEngine app
// cannot read the repo at runtime. For the same reason the DQL's {list_view_limit} and
// {list_max_limit} are filled in here, from the RateXp app's config.yaml, as core's
// publish_to_dynatrace.py does for the published dashboard, and the label templates are
// filled for each group of core's config.yaml labeling.groups, as the clone does (see
// clone_dashboard_from_base.py): sync again after changing either.
//
//   node scripts/sync-dashboard.mjs          write the file
//   node scripts/sync-dashboard.mjs --check  exit 1 when the file differs from the YAML

import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { parse } from "yaml";

const HERE = dirname(fileURLToPath(import.meta.url));
export const DASHBOARD_DIR = join(HERE, "../../../core/modules/dashboard");
export const OUTPUT_FILE = join(HERE, "../ui/app/dashboard/dashboard.json");
export const APP_CONFIG = join(HERE, "../../ratexp/config.yaml");
export const CORE_CONFIG = join(HERE, "../../../core/config.yaml");
const KINDS = ["number", "line", "bar", "count", "table"];
const APP_LIMITS = ["list_view_limit", "list_max_limit"];

const load = (fileName) => parse(readFileSync(join(DASHBOARD_DIR, fileName), "utf-8")) ?? {};

// The RateXp app's row limits, so this app shows and downloads as many ratings as the RateXp app.
export function readAppLimits() {
  const config = parse(readFileSync(APP_CONFIG, "utf-8"));
  return Object.fromEntries(
    APP_LIMITS.map((key) => {
      if (!Number.isInteger(config[key])) throw new Error(`${APP_CONFIG} lacks the number ${key}`);
      return [key, config[key]];
    }),
  );
}

const fillAppLimits = (dql, limits) =>
  dql.replace(/\{(list_view_limit|list_max_limit)\}/g, (_, key) => String(limits[key]));

// Each group of core's labeling.groups, in its order -> the side of each of its values:
// value -> "good" (when_good) or "bad" (when_bad), for a group that splits its values; {}
// for one that does not. core's load_config.py checks them.
export function readLabelGroups() {
  const groups = parse(readFileSync(CORE_CONFIG, "utf-8")).labeling.groups;
  // A list of values, or a mapping of value: description, as its values.
  const valuesOf = (values) => (Array.isArray(values) ? values : Object.keys(values ?? {}));
  return Object.fromEntries(
    Object.entries(groups).map(([name, group]) => [
      name,
      Object.fromEntries([
        ...valuesOf(group.when_good).map((value) => [value, "good"]),
        ...valuesOf(group.when_bad).map((value) => [value, "bad"]),
      ]),
    ]),
  );
}

// Plain objects only: a list, such as hidden_columns, stays as it is, as in the clone.
const isMapping = (value) => value !== null && typeof value === "object" && !Array.isArray(value);

// `value` with {group_words} and {group} replaced in every string, keys too.
function fill(value, group) {
  if (typeof value === "string") {
    return value.replaceAll("{group_words}", group.replaceAll("_", " ")).replaceAll("{group}", group);
  }
  if (isMapping(value)) {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [fill(key, group), fill(item, group)]));
  }
  return value;
}

// `value` with each {labels.<key>} replaced by labels.<key> filled for every group, run together.
function joinLabels(value, templates, groups) {
  if (typeof value === "string") {
    return Object.entries(templates).reduce(
      (text, [key, template]) =>
        text.replaceAll(`{labels.${key}}`, groups.map((group) => fill(template, group)).join("")),
      value,
    );
  }
  if (isMapping(value)) {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, joinLabels(item, templates, groups)]));
  }
  return value;
}

export function cloneDashboard() {
  const ownFile = "dashboard_for_dynatrace.yaml";
  const basePanels = load("dashboard_base.yaml").panels;
  const own = load(ownFile);
  const ownPanels = own.panels ?? {};
  for (const id of Object.keys(basePanels)) {
    if (!(id in ownPanels)) throw new Error(`${ownFile} lacks base panel '${id}'`);
  }
  const labelGroups = readLabelGroups();
  const groups = Object.keys(labelGroups);
  const labelSides = Object.fromEntries(Object.entries(labelGroups).filter(([, sides]) => Object.keys(sides).length));
  const splitGroups = Object.keys(labelSides);
  const { values: valuesTemplate, ...templates } = own.labels ?? {};
  const labelValues = Object.fromEntries(groups.map((group) => [group, fill(valuesTemplate, group)]));
  const filters = { ...own.filters, values: { ...own.filters.values, ...labelValues } };
  const limits = readAppLimits();
  const panels = Object.entries(ownPanels).flatMap(([id, fields]) => {
    const panel = { id, ...basePanels[id], ...fields };
    if (!panel.title || !KINDS.includes(panel.kind)) {
      throw new Error(`${ownFile} panel '${id}' needs a title and a kind in ${KINDS.join(", ")}`);
    }
    return id.includes("{group}") ? splitGroups.map((group) => fill(panel, group)) : [panel];
  });
  const download = joinLabels(own.download, templates, groups);
  return {
    name: own.name,
    filters: joinLabels(filters, templates, groups),
    download: { ...download, dql: fillAppLimits(download.dql, limits) },
    panels: panels.map((panel) => {
      const joined = joinLabels(panel, templates, groups);
      return { ...joined, dql: fillAppLimits(joined.dql, limits) };
    }),
    label_groups: groups,
    label_sides: labelSides,
  };
}

export const render = (dashboard) => `${JSON.stringify(dashboard, null, 2)}\n`;

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const fresh = render(cloneDashboard());
  if (process.argv.includes("--check")) {
    let current = "";
    try {
      current = readFileSync(OUTPUT_FILE, "utf-8");
    } catch {
      // A missing file is out of date too.
    }
    if (current !== fresh) {
      console.error(`${OUTPUT_FILE} is out of date - run npm run sync-dashboard`);
      process.exit(1);
    }
  } else {
    writeFileSync(OUTPUT_FILE, fresh);
  }
}
