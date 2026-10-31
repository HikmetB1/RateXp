import React, { useMemo } from "react";
import { useDql } from "@dynatrace-sdk/react-hooks";
import { Button } from "@dynatrace/strato-components/buttons";
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
import { isoSeconds } from "../dashboard/buildDownload";
import { dashboard, type Panel as PanelSpec } from "../dashboard/loadDashboard";
import { fillFilters, type Filters } from "../dashboard/fillFilters";
import { ratingsPerDay } from "../dashboard/ratingsPerDay";
import type { QueryTimeframe } from "../dashboard/runDql";

export type Row = Record<string, unknown>;

// The panels about skills, which a session rating has none of.
const SKILL_PANELS = new Set(["skills_rated", "percent_good_by_skill"]);
// The web app's Feedback table columns; the feedback panel's DQL returns every one except
// Trajectory, which opens the conversation its request_id names.
const FEEDBACK_COLUMNS = [
  "When", "Type", "Name", "Agent", "Model", "Labels", "Eval", "Score", "Comment", "Trajectory", "Session",
];
// A bar chart row is 32px; the box shows about 5 of them and its value axis, then scrolls.
const BAR_ROW_PX = 32;
const BAR_BOX_PX = 5 * BAR_ROW_PX + 48;

interface PanelProps {
  panel: PanelSpec;
  filters: Filters;
  timeframe: QueryTimeframe;
  onOpenTrajectory: (row: Row) => void;
}

/** One panel: its DQL with the filters filled in, run over the picked timeframe and drawn
 * by its kind - number, line (good vs bad bars per day), bar or the Feedback table. With
 * type session, the skill panels stay and say on top that they do not apply. */
export const Panel = ({ panel, filters, timeframe, onOpenTrajectory }: PanelProps) => {
  const { data, error, isLoading } = useDql<Row>({
    query: fillFilters(panel.dql, dashboard.filters.dql, filters),
    defaultTimeframeStart: timeframe.start,
    defaultTimeframeEnd: timeframe.end,
  });
  const rows = useMemo(() => data?.records ?? [], [data]);
  return (
    <Surface elevation="raised" padding={16} style={{ height: "100%", display: "flex", flexDirection: "column", gap: 12 }}>
      <Heading level={panel.kind === "number" ? 6 : 5}>{panel.title}</Heading>
      {filters.type === "session" && SKILL_PANELS.has(panel.id) && (
        <MessageContainer variant="warning">Does not apply: the type is session, not skill.</MessageContainer>
      )}
      {error ? (
        <MessageContainer variant="critical">{error.message}</MessageContainer>
      ) : (
        <PanelBody panel={panel} rows={rows} loading={isLoading && !data} onOpenTrajectory={onOpenTrajectory} />
      )}
    </Surface>
  );
};

interface PanelBodyProps {
  panel: PanelSpec;
  rows: Row[];
  loading: boolean;
  onOpenTrajectory: (row: Row) => void;
}

const PanelBody = ({ panel, rows, loading, onOpenTrajectory }: PanelBodyProps) => {
  switch (panel.kind) {
    case "number": {
      // Every number panel returns a bare `value`; only the share of good ratings is a
      // percentage. Skills rated reads "n/a: session" for type session.
      const value = rows[0]?.value;
      const number = Number(value);
      return (
        <SingleValue
          data={value == null ? "—" : Number.isNaN(number) ? text(value) : number}
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
      return <FeedbackTable rows={rows} loading={loading} onOpenTrajectory={onOpenTrajectory} />;
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

// percent_good per name, every name worst first as the DQL sorts it; the tooltip adds
// good/total. Past about 5 rows the chart scrolls inside its box.
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
    <div style={{ maxHeight: BAR_BOX_PX, overflowY: "auto" }}>
      <CategoricalBarChart data={data} layout="horizontal" loading={loading} height={Math.max(120, data.length * BAR_ROW_PX)}>
        <CategoricalBarChart.ValueAxis min={0} max={100} label="% good" />
      </CategoricalBarChart>
    </div>
  );
};

interface FeedbackTableProps {
  rows: Row[];
  loading: boolean;
  onOpenTrajectory: (row: Row) => void;
}

// The newest ratings that match the filters, in the web app's Feedback table columns. A
// row with a stored conversation gets a "view" button that opens it in the side panel.
const FeedbackTable = ({ rows, loading, onOpenTrajectory }: FeedbackTableProps) => {
  const columns = useMemo<DataTableColumnDef<Row>[]>(
    () =>
      FEEDBACK_COLUMNS.map((key) =>
        key === "Trajectory"
          ? {
              id: key,
              header: key,
              accessor: "request_id",
              cell: ({ rowData }) => (
                <DataTable.DefaultCell>
                  {rowData.request_id == null ? (
                    "—"
                  ) : (
                    <Button size="condensed" onClick={() => onOpenTrajectory(rowData)}>
                      view
                    </Button>
                  )}
                </DataTable.DefaultCell>
              ),
            }
          : { id: key, header: key, accessor: (row: Row) => cellText(key, row[key]) },
      ),
    [onOpenTrajectory],
  );
  if (!loading && rows.length === 0) return <Muted>No ratings in this range</Muted>;
  return <DataTable data={rows} columns={columns} loading={loading} resizable />;
};

function cellText(column: string, value: unknown): string {
  if (value == null) return "—";
  // Timestamps come back with nanoseconds; the web app shows whole seconds.
  return (column === "When" && isoSeconds(value)) || text(value);
}

// DQL hands back strings, numbers as strings, booleans, and records or arrays as JSON.
export const text = (value: unknown): string => (typeof value === "string" ? value : JSON.stringify(value));

export const Muted = ({ children }: { children: React.ReactNode }) => (
  <Paragraph style={{ color: Colors.Text.Neutral.Subdued }}>{children}</Paragraph>
);
