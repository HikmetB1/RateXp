import React, { useMemo } from "react";
import { useDql } from "@dynatrace-sdk/react-hooks";
import {
  CategoricalBarChart,
  SingleValue,
  TimeseriesChart,
} from "@dynatrace/strato-components/charts";
import { MessageContainer } from "@dynatrace/strato-components/content";
import { Surface } from "@dynatrace/strato-components/layouts";
import { DataTable, type DataTableColumnDef } from "@dynatrace/strato-components/tables";
import { Heading, Paragraph } from "@dynatrace/strato-components/typography";
import Colors from "@dynatrace/strato-design-tokens/colors";
import { dashboard, type Panel as PanelSpec } from "../dashboard/loadDashboard";
import { fillFilters, type Filters } from "../dashboard/fillFilters";
import { ratingsPerDay } from "../dashboard/ratingsPerDay";
import type { QueryTimeframe } from "../dashboard/runDql";

type Row = Record<string, unknown>;

// Columns where a null means the coding agent never wrote the figure, not that it was
// zero - the web app shows the same words.
const NOT_RECORDED = new Set(["steps", "tool_calls", "prompt_tokens", "cached_tokens", "completion_tokens"]);
// A conversation's content is up to 256 KiB of JSON; the cell shows its start.
const CELL_CHARS = 300;

interface PanelProps {
  panel: PanelSpec;
  filters: Filters;
  timeframe: QueryTimeframe;
}

/** One panel: its DQL with the filters filled in, run over the picked timeframe and drawn
 * by its kind - number, line (good vs bad bars per day), bar or table. */
export const Panel = ({ panel, filters, timeframe }: PanelProps) => {
  const { data, error, isLoading } = useDql<Row>({
    query: fillFilters(panel.dql, dashboard.filters.dql, filters),
    defaultTimeframeStart: timeframe.start,
    defaultTimeframeEnd: timeframe.end,
    maxResultBytes: (panel.max_result_megabytes ?? 1) * 1_000_000,
  });
  const rows = useMemo(() => data?.records ?? [], [data]);
  return (
    <Surface elevation="raised" padding={16} style={{ height: "100%", display: "flex", flexDirection: "column", gap: 12 }}>
      <Heading level={panel.kind === "number" ? 6 : 5}>{panel.title}</Heading>
      {error ? (
        <MessageContainer variant="critical">{error.message}</MessageContainer>
      ) : (
        <PanelBody panel={panel} rows={rows} loading={isLoading && !data} />
      )}
    </Surface>
  );
};

const PanelBody = ({ panel, rows, loading }: { panel: PanelSpec; rows: Row[]; loading: boolean }) => {
  switch (panel.kind) {
    case "number": {
      // Every number panel returns a bare `value`; only the share of good ratings is a percentage.
      const value = rows[0]?.value;
      return (
        <SingleValue
          data={value == null ? "—" : Number(value)}
          unit={panel.id === "percent_good" ? "%" : undefined}
          loading={loading}
          height={80}
        />
      );
    }
    case "line":
      return <GoodBadPerDay rows={rows} loading={loading} />;
    case "bar":
      return <PercentGood rows={rows} loading={loading} />;
    default:
      return <Table rows={rows} loading={loading} />;
  }
};

// Good and bad ratings per day, stacked into the day's total as the web app draws them.
const GoodBadPerDay = ({ rows, loading }: { rows: Row[]; loading: boolean }) => {
  const [good, bad] = useMemo(() => ratingsPerDay(rows), [rows]);
  if (!loading && good.datapoints.length === 0) return <Muted>No ratings in this range</Muted>;
  return (
    <TimeseriesChart variant="bar" loading={loading} height={240}>
      <TimeseriesChart.Bar data={good} color={Colors.Charts.Status.Ideal.Default} />
      <TimeseriesChart.Bar data={bad} color={Colors.Charts.Status.Critical.Default} />
    </TimeseriesChart>
  );
};

// percent_good per name, worst first as the DQL sorts it; the tooltip adds good/total.
const PercentGood = ({ rows, loading }: { rows: Row[]; loading: boolean }) => {
  const data = useMemo(
    () =>
      rows.map((r) => ({
        category: `${text(r.name)} (${text(r.good)}/${text(r.total)})`,
        value: Number(r.percent_good) || 0,
        unit: "%",
      })),
    [rows],
  );
  if (!loading && data.length === 0) return <Muted>No rated feedback in this range</Muted>;
  return (
    <CategoricalBarChart data={data} layout="horizontal" loading={loading} height={Math.max(120, data.length * 32)}>
      <CategoricalBarChart.ValueAxis min={0} max={100} label="% good" />
    </CategoricalBarChart>
  );
};

// Every column the panel returns, named after the column with the underscores dropped.
const Table = ({ rows, loading }: { rows: Row[]; loading: boolean }) => {
  const columns = useMemo<DataTableColumnDef<Row>[]>(
    () =>
      Object.keys(rows[0] ?? {}).map((key) => ({
        id: key,
        header: key.replace(/_/g, " "),
        accessor: (row: Row) => cellText(key, row[key]),
      })),
    [rows],
  );
  if (!loading && rows.length === 0) return <Muted>Nothing in this range</Muted>;
  return <DataTable data={rows} columns={columns} loading={loading} sortable resizable />;
};

function cellText(column: string, value: unknown): string {
  if (value == null) return NOT_RECORDED.has(column) ? "not recorded" : "—";
  // Timestamps come back with nanoseconds; the web app shows whole seconds.
  if (column === "created_at") return text(value).replace(/\.\d+Z$/, "Z");
  const full = text(value);
  return full.length > CELL_CHARS ? `${full.slice(0, CELL_CHARS)}…` : full;
}

// DQL hands back strings, numbers as strings, booleans, and records or arrays as JSON.
const text = (value: unknown): string => (typeof value === "string" ? value : JSON.stringify(value));

const Muted = ({ children }: { children: React.ReactNode }) => (
  <Paragraph style={{ color: Colors.Text.Neutral.Subdued }}>{children}</Paragraph>
);
