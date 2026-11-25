import { describe, expect, it } from "vitest";
import { dashboard, FILTER_KEYS } from "../ui/app/dashboard/loadDashboard";
import {
  ALL_FILTERS,
  dqlString,
  fillFilters,
  fillVariables,
  keepListedPicks,
} from "../ui/app/dashboard/fillFilters";

const fragment = dashboard.filters.dql;
// Any variable left unfilled: $type, $skill, ... and one per label group.
const VARIABLE_LEFT = new RegExp(`\\$(${FILTER_KEYS.join("|")})\\b`);

describe("fillFilters", () => {
  it("puts the fragment in the {filters} slot with * for every filter left on all", () => {
    const dql = fillFilters('fetch logs {filters} | limit 1', fragment, ALL_FILTERS);
    expect(dql).not.toContain("{filters}");
    expect(dql).not.toMatch(VARIABLE_LEFT);
    expect(dql.match(/, "\*"\)/g)).toHaveLength(FILTER_KEYS.length);
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
      expect(filled).not.toMatch(VARIABLE_LEFT);
    }
  });

  it("matches a picked label, the conversation's over the rating's, and (none) for an unlabeled rating", () => {
    const dql = fillFilters("{filters}", fragment, { ...ALL_FILTERS, feedback_theme: "Completion is slow", task_type: "(none)" });
    expect(dql).toContain('matchesValue(coalesce(transcript.feedback_theme, ratexp.feedback_theme, "(none)"), "Completion is slow")');
    expect(dql).toContain('matchesValue(coalesce(transcript.task_type, ratexp.task_type, "(none)"), "(none)")');
    expect(dql).toContain('matchesValue(coalesce(transcript.business_case, ratexp.business_case, "(none)"), "*")');
  });

  it("has a dropdown for type, skill, agent, eval and each label group, in that order", () => {
    expect(FILTER_KEYS).toEqual(["type", "skill", "agent", "eval", ...dashboard.label_groups]);
    expect(dashboard.label_groups).toContain("feedback_theme");
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
