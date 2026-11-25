import { readFileSync } from "node:fs";
import { expect, it } from "vitest";
import { parse } from "yaml";
import {
  APP_CONFIG,
  CORE_CONFIG,
  DASHBOARD_DIR,
  OUTPUT_FILE,
  cloneDashboard,
  readLabelGroups,
  render,
} from "../scripts/sync-dashboard.mjs";

it("the bundled dashboard.json is core's YAML as it is now (npm run sync-dashboard)", () => {
  expect(readFileSync(OUTPUT_FILE, "utf-8")).toBe(render(cloneDashboard()));
});

it("carries every base panel, in the order of dashboard_for_dynatrace.yaml, and the download", () => {
  const read = (name) => parse(readFileSync(`${DASHBOARD_DIR}/${name}`, "utf-8"));
  const bundled = JSON.parse(readFileSync(OUTPUT_FILE, "utf-8"));
  const ids = bundled.panels.map((p) => p.id);
  // A {group} panel stands once per label group that splits its values into when_good and when_bad.
  const splitGroups = Object.entries(readLabelGroups())
    .filter(([, sides]) => Object.keys(sides).length)
    .map(([group]) => group);
  const expected = Object.keys(read("dashboard_for_dynatrace.yaml").panels).flatMap((id) =>
    id.includes("{group}") ? splitGroups.map((group) => id.replaceAll("{group}", group)) : [id],
  );
  expect(ids).toEqual(expected);
  for (const id of Object.keys(read("dashboard_base.yaml").panels)) expect(ids).toContain(id);
  expect(bundled.download.dql).toContain("{filters}");
});

it("shows and downloads as many ratings as the RateXp app (its config.yaml limits)", () => {
  const config = parse(readFileSync(APP_CONFIG, "utf-8"));
  const bundled = JSON.parse(readFileSync(OUTPUT_FILE, "utf-8"));
  const feedback = bundled.panels.find((p) => p.id === "feedback");
  expect(feedback.dql).toContain(`| sort timestamp desc | limit ${config.list_view_limit} |`);
  expect(bundled.download.dql).toContain(`| sort timestamp desc | limit ${config.list_max_limit} |`);
  expect(JSON.stringify(bundled)).not.toContain("{list_");
});

it("filters by each label group of core's config.yaml and leaves no template behind", () => {
  const groups = Object.keys(parse(readFileSync(CORE_CONFIG, "utf-8")).labeling.groups);
  const bundled = JSON.parse(readFileSync(OUTPUT_FILE, "utf-8"));
  expect(bundled.label_groups).toEqual(groups);
  // Each value of a group that splits its values has its side, which colors it.
  expect(bundled.label_sides.feedback_theme["Completion is quick"]).toBe("good");
  expect(bundled.label_sides.feedback_theme["Completion is slow"]).toBe("bad");
  expect(bundled.label_sides.language).toBeUndefined();
  for (const group of groups) {
    expect(bundled.filters.values[group]).toContain(`data record(${group}="*")`);
    expect(bundled.filters.dql).toContain(`$${group}`);
  }
  expect(JSON.stringify(bundled)).not.toMatch(/\{labels\.|\{group(_words)?\}/);
  expect(bundled.panels.find((p) => p.id === "feedback").hidden_columns).toEqual(["request_id"]);
});
