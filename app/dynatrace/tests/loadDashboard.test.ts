import { describe, expect, it, vi } from "vitest";
import dashboardJson from "../ui/app/dashboard/dashboard.json";
import {
  type Dashboard,
  dashboard,
  environment,
  fillEnvironment,
  groupTitle,
  labelSide,
} from "../ui/app/dashboard/loadDashboard";

const bundled = dashboardJson as Dashboard;
const match = (env: string) => `coalesce(deployment.environment.name, "prod") == "${env}"`;

describe("fillEnvironment", () => {
  it("keeps the records of one environment in the fragment and every values query that fetches logs", () => {
    const dev = fillEnvironment(bundled, "dev");
    expect(JSON.stringify(dev)).not.toContain("{environment}");
    expect(dev.filters.dql).toContain(match("dev"));
    for (const dql of Object.values(dev.filters.values)) {
      if (dql.includes("fetch logs")) expect(dql).toContain(match("dev"));
    }
  });

  it("leaves the panels and the download as they are, since they take the fragment", () => {
    const dev = fillEnvironment(bundled, "dev");
    expect(dev.panels).toEqual(bundled.panels);
    expect(dev.download).toEqual(bundled.download);
  });

  it("shows prod in an app whose id does not end in .dev", () => {
    expect(environment).toBe("prod");
    expect(dashboard.filters.dql).toContain(match("prod"));
  });

  it("shows dev in the dev copy, whose app id ends in .dev", async () => {
    vi.resetModules();
    vi.doMock("@dynatrace-sdk/app-environment", () => ({ getAppId: () => "my.ratexp.dev" }));
    const devCopy = await import("../ui/app/dashboard/loadDashboard");
    vi.doUnmock("@dynatrace-sdk/app-environment");
    expect(devCopy.environment).toBe("dev");
    expect(devCopy.dashboard.filters.dql).toContain(match("dev"));
  });
});

describe("labels", () => {
  it("heads each label group's column with its name in words", () => {
    expect(groupTitle("business_case")).toBe("Business case");
    expect(groupTitle("feedback_theme")).toBe("Feedback theme");
  });

  it("gives praise the good side and a complaint the bad side, and a plain group's value none", () => {
    expect(labelSide("feedback_theme", "Completion is quick")).toBe("good");
    expect(labelSide("feedback_theme", "Completion is slow")).toBe("bad");
    expect(labelSide("language", "Go")).toBeUndefined();
    expect(labelSide("feedback_theme", null)).toBeUndefined();
  });
});
