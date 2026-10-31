import React, { useMemo } from "react";
import { useDql } from "@dynatrace-sdk/react-hooks";
import { Markdown, MessageContainer } from "@dynatrace/strato-components/content";
import { Flex, PageLayout, Surface } from "@dynatrace/strato-components/layouts";
import { Code, Heading, Paragraph, Strong } from "@dynatrace/strato-components/typography";
import Colors from "@dynatrace/strato-design-tokens/colors";
import { conversationOf, transcriptQueries } from "../dashboard/buildDownload";
import type { QueryTimeframe } from "../dashboard/runDql";
import { Muted, text, type Row } from "./Panel";

// The ATIF fields the panel draws (core/api/build_trajectory.py writes them).
interface Step {
  source?: string;
  message?: unknown;
  reasoning_content?: unknown;
  tool_calls?: { name?: string; arguments?: unknown }[];
  observation?: unknown;
}
interface Atif {
  steps?: Step[];
  oversized?: { message?: string };
  final_metrics?: { total_steps?: number; total_prompt_tokens?: number; total_completion_tokens?: number };
}

interface TrajectoryDetailsProps {
  row: Row; // a Feedback table row whose request_id names its stored conversation
  timeframe: QueryTimeframe;
  onClose: () => void;
}

/** The side panel the Feedback table's "view" opens: the rating's facts, as the web app's
 * trajectory drawer lists them, and its conversation as a timeline. */
export const TrajectoryDetails = ({ row, timeframe, onClose }: TrajectoryDetailsProps) => {
  const { data, error, isLoading } = useDql<Row>({
    query: transcriptQueries([text(row.request_id)])[0],
    defaultTimeframeStart: timeframe.start,
    defaultTimeframeEnd: timeframe.end,
  });
  const record = data?.records[0];
  const atif = useMemo(() => (record ? (conversationOf(record) as Atif) : null), [record]);
  return (
    <PageLayout.Details collapsed={false} onCollapsedChange={(collapsed) => collapsed && onClose()} defaultWidth="40%">
      <Flex flexDirection="column" gap={12} padding={16}>
        <Flex justifyContent="space-between" alignItems="center">
          <Heading level={4}>Trajectory</Heading>
          <PageLayout.Details.ControlBar />
        </Flex>
        <Facts row={row} atif={atif} />
        {error && <MessageContainer variant="critical">{error.message}</MessageContainer>}
        {isLoading && !data && <Muted>Loading...</Muted>}
        {data && !atif && <Muted>The conversation is not in the picked timeframe.</Muted>}
        {atif?.oversized?.message && <MessageContainer variant="warning">{atif.oversized.message}</MessageContainer>}
        {(atif?.steps ?? []).map((step, i) => (
          <StepCard key={i} step={step} />
        ))}
      </Flex>
    </PageLayout.Details>
  );
};

// Type, Name, Agent, Model, Labels, Eval, Score, Steps and Tokens - each when known.
const Facts = ({ row, atif }: { row: Row; atif: Atif | null }) => {
  const metrics = atif?.final_metrics ?? {};
  // Some coding agents (Cursor) write no token counts into their transcripts.
  const tokens =
    metrics.total_prompt_tokens || metrics.total_completion_tokens
      ? `↑ ${metrics.total_prompt_tokens ?? 0} · ↓ ${metrics.total_completion_tokens ?? 0}`
      : "not recorded";
  const facts: [string, unknown][] = [
    ["Type", row.Type],
    ["Name", row.Type === "skill" ? row.Name : null],
    ["Agent", row.Agent],
    ["Model", row.Model],
    ["Labels", row.Labels],
    ["Eval", row.Eval],
    ["Score", row.Score],
    ["Steps", atif ? (metrics.total_steps ?? atif.steps?.length ?? 0) : null],
    ["Tokens", atif ? tokens : null],
  ];
  return (
    <Flex gap={16} flexWrap="wrap">
      {facts
        .filter(([, value]) => value != null)
        .map(([key, value]) => (
          <Flex key={key} flexDirection="column" gap={2}>
            <Paragraph style={{ color: Colors.Text.Neutral.Subdued, fontSize: 12 }}>{key}</Paragraph>
            <Code>{text(value)}</Code>
          </Flex>
        ))}
    </Flex>
  );
};

// One step: who spoke, any reasoning, the message, the tools it called and their output.
const StepCard = ({ step }: { step: Step }) => (
  <Surface elevation="flat" padding={12} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
    <Strong style={{ textTransform: "uppercase", fontSize: 12 }}>{step.source}</Strong>
    {step.reasoning_content != null && (
      <details open>
        <summary>reasoning</summary>
        <Markdown>{text(step.reasoning_content)}</Markdown>
      </details>
    )}
    {step.message != null && <Markdown>{text(step.message)}</Markdown>}
    {(Array.isArray(step.tool_calls) ? step.tool_calls : []).map((call, i) => (
      <details key={i} open>
        <summary>
          <Code>⌗ {call.name}</Code>
        </summary>
        {call.arguments != null && (
          <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", margin: 0 }}>
            {JSON.stringify(call.arguments, null, 2)}
          </pre>
        )}
      </details>
    ))}
    {step.observation != null && (
      <details open>
        <summary>↳ output</summary>
        <Markdown>{text(step.observation)}</Markdown>
      </details>
    )}
  </Surface>
);
