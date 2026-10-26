import React, { useState } from "react";
import { useDql } from "@dynatrace-sdk/react-hooks";
import { Button } from "@dynatrace/strato-components/buttons";
import type { Timeframe } from "@dynatrace/strato-components/core";
import { MessageContainer } from "@dynatrace/strato-components/content";
import { TimeframeSelector } from "@dynatrace/strato-components/filters";
import { FormField, Label, Select } from "@dynatrace/strato-components/forms";
import { Flex, Grid } from "@dynatrace/strato-components/layouts";
import { DownloadIcon } from "@dynatrace/strato-icons";
import { Panel } from "../components/Panel";
import { downloadRows, TRANSCRIPT_RESULT_MEGABYTES, transcriptQueries } from "../dashboard/buildDownload";
import { ALL_FILTERS, fillFilters, type Filters } from "../dashboard/fillFilters";
import { dashboard, FILTER_KEYS, type FilterKey, type PanelKind } from "../dashboard/loadDashboard";
import { runDql, type QueryTimeframe } from "../dashboard/runDql";

// 30 days, as the web app and the published Dynatrace dashboard open on.
const DEFAULT_TIMEFRAME = { from: "now()-30d", to: "now()" };
const DAY_MS = 24 * 3600e3;
// Out of 12 columns: four number tiles to a row, three bars to a row, the rest full width.
const SPAN: Record<PanelKind, number> = { number: 3, bar: 4, line: 12, table: 12 };
const ALL = "*"; // the first row of every dropdown query, meaning all

const defaultQueryTimeframe = (): QueryTimeframe => ({
  start: new Date(Date.now() - 30 * DAY_MS).toISOString(),
  end: new Date().toISOString(),
});

/** The web app's Dashboard view: the skill / agent / eval / label filters and a timeframe over
 * every panel in dashboard.json, and the trajectory download. */
export const Dashboard = () => {
  const [filters, setFilters] = useState<Filters>(ALL_FILTERS);
  const [timeframe, setTimeframe] = useState<QueryTimeframe>(defaultQueryTimeframe);
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  const onTimeframe = (value: Timeframe | null) => {
    setTimeframe(
      value
        ? { start: value.from.absoluteDate, end: value.to.absoluteDate }
        : defaultQueryTimeframe(),
    );
  };

  // The newest 1000 ratings matching the filters, each with its conversation, saved as one
  // JSON file in the web app's shape (see buildDownload.ts).
  const download = async () => {
    setDownloading(true);
    setDownloadError(null);
    try {
      const ratings = await runDql(
        fillFilters(dashboard.download.dql, dashboard.filters.dql, filters),
        timeframe,
      );
      const ids = ratings.map((r) => r.request_id).filter((id): id is string => typeof id === "string");
      const transcripts = (
        await Promise.all(
          transcriptQueries(ids).map((q) => runDql(q, timeframe, TRANSCRIPT_RESULT_MEGABYTES)),
        )
      ).flat();
      saveJson(downloadRows(ratings, transcripts), "ratexp-feedback.json");
    } catch (e) {
      setDownloadError(e instanceof Error ? e.message : String(e));
    } finally {
      setDownloading(false);
    }
  };

  return (
    <Flex flexDirection="column" gap={16} padding={16}>
      <Flex alignItems="flex-end" gap={12} flexWrap="wrap">
        {FILTER_KEYS.map((key) => (
          <FilterSelect
            key={key}
            filterKey={key}
            value={filters[key]}
            onChange={(value) => setFilters({ ...filters, [key]: value })}
          />
        ))}
        <TimeframeSelector defaultValue={DEFAULT_TIMEFRAME} onChange={onTimeframe} />
        <Button
          variant="emphasized"
          onClick={() => void download()}
          loading={downloading}
          style={{ marginLeft: "auto" }}
        >
          <Button.Prefix>
            <DownloadIcon />
          </Button.Prefix>
          Download trajectories
        </Button>
      </Flex>
      {downloadError && <MessageContainer variant="critical">{downloadError}</MessageContainer>}
      <Grid gridTemplateColumns="repeat(12, minmax(0, 1fr))" gap={16}>
        {dashboard.panels.map((panel) => (
          <div key={panel.id} style={{ gridColumn: `span ${SPAN[panel.kind]}` }}>
            <Panel panel={panel} filters={filters} timeframe={timeframe} />
          </div>
        ))}
      </Grid>
    </Flex>
  );
};

interface FilterSelectProps {
  filterKey: FilterKey;
  value: string | null;
  onChange: (value: string | null) => void;
}

// One dropdown, filled by its filters.values query: "*" first, which shows as All.
const FilterSelect = ({ filterKey, value, onChange }: FilterSelectProps) => {
  const { data } = useDql({ query: dashboard.filters.values[filterKey] });
  const options = (data?.records ?? [])
    .map((r) => r?.[filterKey])
    .filter((v): v is string => typeof v === "string" && v !== ALL);
  return (
    <FormField>
      <Label>{filterKey.replace("_", " ")}</Label>
      <Select
        name={`filter-${filterKey}`}
        value={value ?? ALL}
        onChange={(picked) => onChange(picked === ALL || picked == null ? null : picked)}
      >
        <Select.Content>
          <Select.Option value={ALL}>All</Select.Option>
          {options.map((option) => (
            <Select.Option key={option} value={option}>
              {option}
            </Select.Option>
          ))}
        </Select.Content>
      </Select>
    </FormField>
  );
};

function saveJson(rows: unknown, fileName: string) {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(rows, null, 2)], { type: "application/json;charset=utf-8" }),
  );
  const a = document.createElement("a");
  a.href = url;
  a.download = fileName;
  a.click();
  URL.revokeObjectURL(url);
}
