// Clone core's dashboard_base.yaml into the Dynatrace dashboard, as
// core/modules/dashboard/clone_dashboard_from_base.py does, and write it to
// ui/app/dashboard/dashboard.json - the file the app bundles, since an AppEngine app
// cannot read the repo at runtime. For the same reason the DQL's {list_view_limit} and
// {list_max_limit} are filled in here, from the RateXp app's config.yaml, as core's
// publish_to_dynatrace.py does for the published dashboard.
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
const KINDS = ["number", "line", "bar", "table"];
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

export function cloneDashboard() {
  const ownFile = "dashboard_for_dynatrace.yaml";
  const basePanels = load("dashboard_base.yaml").panels;
  const own = load(ownFile);
  const ownPanels = own.panels ?? {};
  for (const id of Object.keys(basePanels)) {
    if (!(id in ownPanels)) throw new Error(`${ownFile} lacks base panel '${id}'`);
  }
  const limits = readAppLimits();
  const panels = Object.entries(ownPanels).map(([id, fields]) => {
    const panel = { id, ...basePanels[id], ...fields };
    if (!panel.title || !KINDS.includes(panel.kind)) {
      throw new Error(`${ownFile} panel '${id}' needs a title and a kind in ${KINDS.join(", ")}`);
    }
    return { ...panel, dql: fillAppLimits(panel.dql, limits) };
  });
  const download = { ...own.download, dql: fillAppLimits(own.download.dql, limits) };
  return { name: own.name, filters: own.filters, download, panels };
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
