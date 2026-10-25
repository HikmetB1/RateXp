import { queryExecutionClient } from "@dynatrace-sdk/client-query";

export interface QueryTimeframe {
  start: string; // ISO8601
  end: string;
}

/** One DQL query's records, run as the logged-in user: execute, then poll until done.
 * For the download, which runs once on a click; the panels use useDql instead. */
export async function runDql(
  query: string,
  timeframe: QueryTimeframe,
  maxResultMegabytes = 1,
): Promise<Record<string, unknown>[]> {
  const started = await queryExecutionClient.queryExecute({
    body: {
      query,
      defaultTimeframeStart: timeframe.start,
      defaultTimeframeEnd: timeframe.end,
      maxResultRecords: 1000,
      maxResultBytes: maxResultMegabytes * 1_000_000,
      requestTimeoutMilliseconds: 30_000,
    },
  });
  let { result, state } = started;
  while (!result && (state === "RUNNING" || state === "NOT_STARTED") && started.requestToken) {
    ({ result, state } = await queryExecutionClient.queryPoll({
      requestToken: started.requestToken,
      requestTimeoutMilliseconds: 30_000,
    }));
  }
  if (!result) throw new Error(`the query ended ${state}`);
  return result.records.filter((r) => r !== null);
}
