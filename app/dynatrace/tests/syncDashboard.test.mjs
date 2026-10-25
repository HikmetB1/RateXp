import { readFileSync } from "node:fs";
import { expect, it } from "vitest";
import { parse } from "yaml";
import { DASHBOARD_DIR, OUTPUT_FILE, cloneDashboard, render } from "../scripts/sync-dashboard.mjs";

it("the bundled dashboard.json is core's YAML as it is now (npm run sync-dashboard)", () => {
  expect(readFileSync(OUTPUT_FILE, "utf-8")).toBe(render(cloneDashboard()));
});

it("carries every base panel, in the order of dashboard_for_dynatrace.yaml, and the download", () => {
  const read = (name) => parse(readFileSync(`${DASHBOARD_DIR}/${name}`, "utf-8"));
  const bundled = JSON.parse(readFileSync(OUTPUT_FILE, "utf-8"));
  const ids = bundled.panels.map((p) => p.id);
  expect(ids).toEqual(Object.keys(read("dashboard_for_dynatrace.yaml").panels));
  for (const id of Object.keys(read("dashboard_base.yaml").panels)) expect(ids).toContain(id);
  expect(bundled.download.dql).toContain("{filters}");
});
