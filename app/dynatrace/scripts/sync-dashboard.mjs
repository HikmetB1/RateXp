// Clone core's dashboard_base.yaml into the Dynatrace dashboard, as
// core/modules/dashboard/clone_dashboard_from_base.py does, and write it to
// ui/app/dashboard/dashboard.json - the file the app bundles, since an AppEngine app
// cannot read the repo at runtime.
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
const KINDS = ["number", "line", "bar", "table"];

const load = (fileName) => parse(readFileSync(join(DASHBOARD_DIR, fileName), "utf-8")) ?? {};

export function cloneDashboard() {
  const ownFile = "dashboard_for_dynatrace.yaml";
  const basePanels = load("dashboard_base.yaml").panels;
  const own = load(ownFile);
  const ownPanels = own.panels ?? {};
  for (const id of Object.keys(basePanels)) {
    if (!(id in ownPanels)) throw new Error(`${ownFile} lacks base panel '${id}'`);
  }
  const panels = Object.entries(ownPanels).map(([id, fields]) => {
    const panel = { id, ...basePanels[id], ...fields };
    if (!panel.title || !KINDS.includes(panel.kind)) {
      throw new Error(`${ownFile} panel '${id}' needs a title and a kind in ${KINDS.join(", ")}`);
    }
    return panel;
  });
  return { name: own.name, filters: own.filters, download: own.download, panels };
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
