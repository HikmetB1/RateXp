import { dqlString } from "./fillFilters";

// What "Download trajectories" saves: the same rows, keys and order as the web app's
// /dashboard/export (app/ratexp/api/run_dashboard_panels.py export_feedback).

type Row = Record<string, unknown>;

// 50 trajectories of up to 256 KiB each (core's max_transcript_bytes) fit one query's
// 20 MB result; past 1 MB Dynatrace cuts the rows and only warns.
export const TRANSCRIPTS_PER_QUERY = 50;
export const TRANSCRIPT_RESULT_MEGABYTES = 20;

/** The DQL fetching the transcripts for these request ids, one query per 50 ids. */
export function transcriptQueries(requestIds: string[]): string[] {
  const queries: string[] = [];
  for (let i = 0; i < requestIds.length; i += TRANSCRIPTS_PER_QUERY) {
    const ids = requestIds.slice(i, i + TRANSCRIPTS_PER_QUERY).map(dqlString).join(", ");
    queries.push(
      `fetch logs | filter ratexp.record_type == "transcript" and in(ratexp.request_id, ${ids})` +
        " | sort timestamp desc | fields request_id=ratexp.request_id," +
        " schema_version=ratexp.schema_version, content",
    );
  }
  return queries;
}

const text = (value: unknown): string | null => (typeof value === "string" ? value : null);

/** A Dynatrace nanosecond timestamp trimmed to whole seconds + Z, PostgreSQL's shape. */
export function isoSeconds(value: unknown): string | null {
  const ts = text(value);
  return ts === null ? null : `${ts.split(".", 1)[0].replace(/Z$/, "")}Z`;
}

/** The trajectory a transcript log carries in its content, or a stub with no steps when
 * the content is not the ATIF JSON object - as the web app's Dynatrace reader does. */
export function conversationOf(transcript: Row): unknown {
  try {
    const atif: unknown = JSON.parse(text(transcript.content) ?? "");
    if (atif !== null && typeof atif === "object" && !Array.isArray(atif)) return atif;
  } catch {
    // Not JSON: fall through to the stub.
  }
  return { schema_version: text(transcript.schema_version), steps: [] };
}

/** One entry per rating, newest first, with its conversation: the transcript posted under
 * the same request_id (the newest, should there be two), or null. */
export function downloadRows(ratings: Row[], transcripts: Row[]): Row[] {
  const conversations = new Map<string, unknown>();
  for (const t of transcripts) {
    const id = text(t.request_id);
    if (id !== null && !conversations.has(id)) conversations.set(id, conversationOf(t));
  }
  return ratings.map((r) => {
    const score = Number(r.score);
    const requestId = text(r.request_id);
    return {
      created_at: isoSeconds(r.created_at),
      session_id: text(r.session_id),
      skill_name: text(r.skill_name),
      name: text(r.skill_name) ?? text(r.session_id),
      agent: text(r.agent),
      eval_name: text(r.eval_name),
      score: r.score == null || Number.isNaN(score) ? null : score,
      comment: text(r.comment),
      request_id: requestId,
      business_case: text(r.business_case),
      language: text(r.language),
      task_type: text(r.task_type),
      conversation: (requestId !== null && conversations.get(requestId)) || null,
    };
  });
}
