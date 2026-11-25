import { describe, expect, it } from "vitest";
import {
  TRANSCRIPTS_PER_QUERY,
  downloadRows,
  isoSeconds,
  transcriptQueries,
} from "../ui/app/dashboard/buildDownload";

const rating = {
  created_at: "2026-10-25T15:21:06.123456789Z",
  session_id: "s1",
  skill_name: null,
  agent: "cursor",
  eval_name: "human-satisfaction",
  score: "1",
  comment: "fine",
  request_id: "r1",
  business_case: "Backend",
  language: "Go",
  task_type: null,
  feedback_theme: "Completion is quick",
};

describe("downloadRows", () => {
  it("keeps the web app's keys and order, names a whole-session rating after its session", () => {
    const [row] = downloadRows([rating], []);
    expect(Object.keys(row)).toEqual([
      "created_at", "session_id", "skill_name", "name", "agent", "eval_name",
      "score", "comment", "request_id", "labels", "conversation",
    ]);
    expect(row).toMatchObject({
      created_at: "2026-10-25T15:21:06Z", name: "s1", score: 1, conversation: null,
    });
    // One object, as the web app's: the label group columns that hold a value, in config order.
    expect(row.labels).toEqual({ business_case: "Backend", language: "Go", feedback_theme: "Completion is quick" });
    expect(Object.keys(row.labels as object)).toEqual(["business_case", "language", "feedback_theme"]);
  });

  it("attaches the newest transcript with the same request_id, and a stub for non-JSON content", () => {
    const transcripts = [
      { request_id: "r1", schema_version: "ATIF-v1.7", content: '{"schema_version":"ATIF-v1.7","steps":[1]}' },
      { request_id: "r1", schema_version: "ATIF-v1.7", content: '{"steps":["older"]}' },
      { request_id: "r2", schema_version: "ATIF-v1.7", content: "not json" },
    ];
    const rows = downloadRows([rating, { ...rating, request_id: "r2", score: null }], transcripts);
    expect(rows[0].conversation).toEqual({ schema_version: "ATIF-v1.7", steps: [1] });
    expect(rows[1].conversation).toEqual({ schema_version: "ATIF-v1.7", steps: [] });
    expect(rows[1].score).toBeNull();
  });

  it("never pairs by session: a rating without a request_id has no conversation", () => {
    const [row] = downloadRows([{ ...rating, request_id: null }], [{ request_id: "r1", content: "{}" }]);
    expect(row.conversation).toBeNull();
  });
});

describe("transcriptQueries", () => {
  it("asks for 50 request ids per query, quoted", () => {
    const ids = Array.from({ length: TRANSCRIPTS_PER_QUERY + 1 }, (_, i) => `id"${i}`);
    const queries = transcriptQueries(ids);
    expect(queries).toHaveLength(2);
    expect(queries[0]).toContain('in(ratexp.request_id, "id\\"0", ');
    expect(queries[1]).toContain(`"id\\"${TRANSCRIPTS_PER_QUERY}")`);
    expect(transcriptQueries([])).toEqual([]);
  });
});

it("isoSeconds trims nanoseconds and passes non-strings as null", () => {
  expect(isoSeconds("2026-10-25T15:21:06.000000000Z")).toBe("2026-10-25T15:21:06Z");
  expect(isoSeconds(null)).toBeNull();
});
