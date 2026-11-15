// Deploy the dev copy of the RateXp Dynatrace app beside the prod one: the same build
// under the app id <id>.dev, named "<name> (dev)". Installing the dev copy thus never
// replaces the prod app, and the dev copy reads its own id to show the records that core
// marks dev (ui/app/dashboard/loadDashboard.ts).
//
// dt-app takes the app id only from app.config.json. Thus this script changes the file for
// the deploy and puts the file back after, also when the deploy fails or stops.
//
//   npm run deploy:dev

import { spawnSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const APP_DIR = join(dirname(fileURLToPath(import.meta.url)), "..");
const CONFIG_FILE = join(APP_DIR, "app.config.json");

const original = readFileSync(CONFIG_FILE, "utf-8");
const config = JSON.parse(original);
// Only a killed run can leave the dev id behind; deploying from it would make <id>.dev.dev.
if (config.app.id.endsWith(".dev")) {
  console.error(`${CONFIG_FILE} already holds the dev id ${config.app.id} - restore it with git first`);
  process.exit(1);
}
config.app.id = `${config.app.id}.dev`;
config.app.name = `${config.app.name} (dev)`;

// Ctrl-C or a closed terminal also reaches npm, which stops the deploy; this process ignores
// the signal and waits to put the file back.
for (const signal of ["SIGINT", "SIGTERM", "SIGHUP"]) process.on(signal, () => {});
writeFileSync(CONFIG_FILE, `${JSON.stringify(config, null, 2)}\n`);
let status = 1;
try {
  status = spawnSync("npm", ["run", "deploy"], { cwd: APP_DIR, stdio: "inherit" }).status ?? 1;
} finally {
  writeFileSync(CONFIG_FILE, original);
}
process.exit(status);
