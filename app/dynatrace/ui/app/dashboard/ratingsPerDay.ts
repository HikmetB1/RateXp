// The good_bad_over_time rows ({day, good, bad}, one per rated day) as two series with a
// datapoint for every day from the first rated one to the last, zero on days nobody
// rated, as the web app's stacked bars draw them.

const DAY_MS = 24 * 3600e3;

type Row = Record<string, unknown>;

// An index signature, so a DaySeries is a Strato Timeseries as it stands.
export interface DaySeries extends Record<string, unknown> {
  name: "good" | "bad";
  datapoints: { start: Date; end: Date; value: number }[];
}

export function ratingsPerDay(rows: Row[]): DaySeries[] {
  // DQL buckets by UTC day; the first 10 characters are that day's date.
  const byDate = new Map(rows.map((r) => [typeof r.day === "string" ? r.day.slice(0, 10) : "", r]));
  const dates = [...byDate.keys()].sort();
  const good: DaySeries = { name: "good", datapoints: [] };
  const bad: DaySeries = { name: "bad", datapoints: [] };
  if (dates.length > 0) {
    const last = Date.parse(dates[dates.length - 1]);
    for (let t = Date.parse(dates[0]); t <= last; t += DAY_MS) {
      const row = byDate.get(new Date(t).toISOString().slice(0, 10));
      const span = { start: new Date(t), end: new Date(t + DAY_MS) };
      good.datapoints.push({ ...span, value: Number(row?.good) || 0 });
      bad.datapoints.push({ ...span, value: Number(row?.bad) || 0 });
    }
  }
  return [good, bad];
}
