import { describe, expect, it } from "vitest";
import { dashboard } from "../ui/app/dashboard/loadDashboard";
import {
  ALL_FILTERS,
  dqlString,
  fillFilters,
  fillVariables,
  keepListedPicks,
} from "../ui/app/dashboard/fillFilters";

const fragment = dashboard.filters.dql;

describe("fillFilters", () => {
  it("puts the fragment in the {filters} slot with * for every filter left on all", () => {
    const dql = fillFilters('fetch logs {filters} | limit 1', fragment, ALL_FILTERS);
    expect(dql).not.toContain("{filters}");
    expect(dql).not.toMatch(/\$(type|skill|agent|eval|business_case|language|task_type)\b/);
    expect(dql.match(/, "\*"\)/g)).toHaveLength(7);
  });

  it("matches a picked type against whether the rating has a skill", () => {
    const dql = fillFilters("{filters}", fragment, { ...ALL_FILTERS, type: "session" });
    expect(dql).toContain('matchesValue(if(isNull(ratexp.skill_name), "session", else:"skill"), "session")');
  });

  it("fills a variable the panel itself names, outside the fragment", () => {
    const skillsRated = dashboard.panels.find((p) => p.id === "skills_rated")!.dql;
    const dql = fillFilters(skillsRated, fragment, { ...ALL_FILTERS, type: "session" });
    expect(dql).toContain('if("session" == "session", "n/a: session", else:toString(value))');
  });

  it("matches a picked value, and (none) through the coalesce for a null skill or eval", () => {
    const dql = fillFilters("{filters}", fragment, { ...ALL_FILTERS, skill: "(none)", agent: "claude" });
    expect(dql).toContain('matchesValue(coalesce(ratexp.skill_name, "(none)"), "(none)")');
    expect(dql).toContain('matchesValue(splitString(ratexp.agent, " ")[0], "claude")');
    expect(dql).toContain('matchesValue(coalesce(ratexp.eval_name, "(none)"), "*")');
  });

  it("escapes quotes and backslashes, and leaves a $ in a value alone", () => {
    expect(dqlString('a"b\\c')).toBe('"a\\"b\\\\c"');
    const dql = fillFilters("{filters}", fragment, { ...ALL_FILTERS, skill: "x$&y" });
    expect(dql).toContain('"x$&y"');
  });

  it("fills every shipped panel and the download, leaving no slot or variable behind", () => {
    for (const dql of [...dashboard.panels.map((p) => p.dql), dashboard.download.dql]) {
      const filled = fillFilters(dql, fragment, ALL_FILTERS);
      expect(filled).not.toContain("{filters}");
      expect(filled).not.toMatch(/\$(type|skill|agent|eval|business_case|language|task_type)\b/);
    }
  });

  it("matches a picked label, and (none) for a rating without a labeled conversation", () => {
    const dql = fillFilters("{filters}", fragment, { ...ALL_FILTERS, language: "go", task_type: "(none)" });
    expect(dql).toContain('matchesValue(coalesce(transcript.language, "(none)"), "go")');
    expect(dql).toContain('matchesValue(coalesce(transcript.task_type, "(none)"), "(none)")');
    expect(dql).toContain('matchesValue(coalesce(transcript.business_case, "(none)"), "*")');
  });
});

describe("the dropdowns", () => {
  it("narrow every values query but type's to the picked type", () => {
    for (const [key, dql] of Object.entries(dashboard.filters.values)) {
      const filled = fillVariables(dql, { ...ALL_FILTERS, type: "skill" });
      expect(filled).not.toContain("$type");
      if (key !== "type") expect(filled, key).toContain('else:"skill"), "skill")');
    }
  });

  it("drop a pick the narrowed list no longer holds, and keep the object when it does", () => {
    const picked = { ...ALL_FILTERS, type: "session", agent: "claude-code" };
    expect(keepListedPicks(picked, "agent", ["cursor"])).toEqual({ ...picked, agent: null });
    expect(keepListedPicks(picked, "agent", ["claude-code", "cursor"])).toBe(picked);
    expect(keepListedPicks(picked, "eval", [])).toBe(picked); // nothing picked: nothing to drop
  });
});
