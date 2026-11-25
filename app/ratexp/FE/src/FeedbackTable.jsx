// The Feedback table both views draw - Query & table's rows (GET /feedback, POST /query) and
// the Dashboard's Feedback panel - with the cells and badges the trajectory drawer reuses.

import { Fragment } from 'react'

// One row per rating. `transcriptFor` finds a row's stored conversation (or nothing);
// `onOpen(transcript, row)` opens it in the trajectory drawer. `labelGroups` gives the
// Labels columns, one per group in core/config.yaml's order, and `labelSides` the side of
// each value of a group that splits its values (both from GET /meta).
export function FeedbackTable({ rows, transcriptFor, onOpen, labelGroups = [], labelSides = {}, style }) {
  // With label groups the header takes two rows: Labels over one column per group.
  const nested = labelGroups.length > 0
  const span = nested ? 2 : undefined
  return (
    // Narrow windows show the rows as cards (index.css); a row still too wide for the
    // card scrolls sideways inside it instead of overflowing.
    <div className="table-scroll" style={style}>
      <table className="data-table" style={{ borderCollapse: 'collapse', width: '100%', fontSize: 14 }}>
        <thead>
          <tr>
            <Th rowSpan={span}>When</Th>
            <Th rowSpan={span}>Type</Th>
            <Th rowSpan={span}>Name</Th>
            <Th rowSpan={span}>Agent</Th>
            <Th rowSpan={span}>Model</Th>
            {nested && <Th colSpan={labelGroups.length} className="th-group">Labels</Th>}
            <Th rowSpan={span}>Eval</Th>
            <Th rowSpan={span}>Score</Th>
            <Th rowSpan={span}>Comment</Th>
            <Th rowSpan={span}>Trajectory</Th>
          </tr>
          {nested && (
            <tr>
              {labelGroups.map((group) => <Th key={group} className="th-sub">{groupTitle(group)}</Th>)}
            </tr>
          )}
        </thead>
        <tbody>
          {rows.map((r, i) => {
            const transcript = transcriptFor(r)
            const model = modelOf(r, transcript)
            const labels = labelsOf(r, transcript)
            return (
              <tr key={i}>
                <Td label="When" className="td-nowrap"><When at={r.created_at} /></Td>
                <Td label="Type"><TypeBadge skillName={r.skill_name} /></Td>
                <Td label="Name" className="td-id"><Name row={r} /></Td>
                <Td label="Agent"><code><Words text={r.agent} /></code></Td>
                <Td label="Model">{model ? <code><Words text={model} /></code> : <Dash />}</Td>
                {labelGroups.map((group) => (
                  <Td key={group} label={groupTitle(group)}>
                    <LabelValue value={labels[group]} side={labelSides[group]?.[labels[group]]} />
                  </Td>
                ))}
                {/* No Words here: unlike the other names, an eval name may break after a
                    hyphen ("human-" / "satisfaction"), which keeps the Eval column narrow. */}
                <Td label="Eval">{r.eval_name ? <code>{r.eval_name}</code> : <Dash />}</Td>
                <Td label="Score">{scoreLabel(r.score)}</Td>
                <Td label="Comment">{r.comment ? <span className="neutral">{r.comment}</span> : <Dash />}</Td>
                <Td label="Trajectory"><Trajectory transcript={transcript} onOpen={(t) => onOpen(t, r)} /></Td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

// The timestamp as the date over the time ("2026-11-22" / "18:36:50Z"), which keeps the
// When column narrow. A timestamp without a "T" stays on one line.
function When({ at }) {
  if (!at) return <Dash />
  const [date, time] = String(at).split('T')
  return time ? <span>{date}<br />{time}</span> : at
}

// A session rating's name is its session id. A skill rating's name is the skill, with
// the session id in small type under it, so the table needs no Session column.
function Name({ row }) {
  if (!row.name) return <Dash />
  if (!row.skill_name) return <code style={{ fontSize: 11 }}>{row.name}</code>
  return (
    <>
      <code><Words text={row.name} /></code>
      {row.session_id && <code className="name-session">{row.session_id}</code>}
    </>
  )
}

// Claude Code records the model per turn inside the trajectory, so it is known
// for rows whose conversation was consented. Runtimes that put it in the agent
// label instead (Cursor posts "cursor gpt-5", the seeder "langchain gpt-4o-mini")
// are read from there, shared or not.
function modelOf(r, transcript) {
  const fromTrajectory = transcript?.atif?.agent?.model_name
  if (fromTrajectory) return fromTrajectory
  return String(r.agent || '').split(' ')[1] || null
}

// Each row links to its trajectory, opened in a slide-over drawer (App.jsx's
// TrajectoryDrawer), plus a download button that saves just this row's ATIF as a JSON file.
function Trajectory({ transcript, onOpen }) {
  const steps = transcript?.atif?.steps ?? []
  const oversized = transcript?.atif?.oversized
  // No steps and no oversized note means there's simply no trajectory to show.
  if (steps.length === 0 && !oversized) return <Dash />

  // Save this single trajectory's ATIF to a JSON file (no server round-trip - we
  // already have it). Named by session id so multiple downloads don't collide.
  const downloadTrajectory = () => {
    const json = JSON.stringify(transcript.atif, null, 2)
    const url = URL.createObjectURL(new Blob([json], { type: 'application/json;charset=utf-8' }))
    const a = document.createElement('a')
    a.href = url
    a.download = `trajectory-${transcript.atif?.session_id ?? 'export'}.json`
    a.click()
    URL.revokeObjectURL(url)
  }

  // Blue chip opens the drawer; orange chip downloads the trajectory JSON.
  const actions = (
    <span className="tx-actions">
      <button
        className="tx-chip"
        onClick={() => onOpen(transcript)}
        title={oversized ? 'Trajectory too large to store - open for details' : `Open trajectory - ${steps.length} steps`}
      >
        {/* Chat glyph + sliding arrow; the step count lives in the drawer header. */}
        <svg className="tx-chip-ico" viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
          <path
            d="M3 2.8h10a1.6 1.6 0 0 1 1.6 1.6v5.2a1.6 1.6 0 0 1-1.6 1.6H7l-3 2.8v-2.8H3a1.6 1.6 0 0 1-1.6-1.6V4.4A1.6 1.6 0 0 1 3 2.8Z"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.3"
            strokeLinejoin="round"
          />
        </svg>
        <span className="tx-chip-arrow" aria-hidden="true">→</span>
      </button>
      <button
        className="tx-chip tx-chip-dl"
        onClick={downloadTrajectory}
        title="Download this trajectory as JSON"
        aria-label="Download trajectory JSON"
      >
        {/* Download glyph: a down arrow dropping into a tray. */}
        <svg className="tx-chip-ico" viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
          <path d="M8 2v7" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
          <path d="M5.2 6.4 8 9.2l2.8-2.8" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M3 10.6v1.4A1.4 1.4 0 0 0 4.4 13.4h7.2A1.4 1.4 0 0 0 13 12v-1.4" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
    </span>
  )

  if (!oversized) return actions
  // Oversized: stack a short red alert under the buttons so it's obvious at a glance.
  return (
    <span className="tx-cell">
      {actions}
      <span className="tx-large-alert">! large trajectory</span>
    </span>
  )
}

// Cell styling lives in index.css (.th/.td) so the narrow-window breakpoint can restyle
// the table into cards. `label` becomes data-label, the card row's heading there;
// `className` adds how the cell wraps (.td-nowrap, .td-id).
function Th({ children, className, ...span }) { return <th className={className ? `th ${className}` : 'th'} {...span}>{children}</th> }
function Td({ children, label, className }) { return <td className={className ? `td ${className}` : 'td'} data-label={label}>{children}</td> }

// A name that wraps only between its words, never after a hyphen: "claude-code" stays
// whole, while an agent label like "langchain gpt-4o-mini" may take two lines, which
// keeps the whole table inside its card.
function Words({ text }) {
  return String(text).split(' ').map((word, i) => (
    <Fragment key={i}>{i > 0 && ' '}<span className="word">{word}</span></Fragment>
  ))
}
function Dash() { return <span style={{ color: 'var(--faint)' }}>—</span> }

// A rating's labels as {group: value}: its own, and over them, group by group, its stored
// conversation's, as core's feedback_with_labels view joins them.
export function labelsOf(row, transcript) {
  return { ...row?.labels, ...transcript?.labels }
}

// A label group's name as a heading: "business_case" -> "Business case".
export function groupTitle(group) {
  const words = group.replaceAll('_', ' ')
  return words.charAt(0).toUpperCase() + words.slice(1)
}

// One label value: green for a good side (praise), red for a bad side (complaint), and blue
// for a value of a group that does not split its values. A dash when the group has none.
export function LabelValue({ value, side }) {
  if (!value) return <Dash />
  return <code className={side ? `label-${side}` : undefined}>{value}</code>
}

// What the rating is about. A skill rating is named after the skill; a whole-session
// rating is about no one skill and arrives without a name, which is what tells the
// two apart. Same plain-text look as ScoreBadge, in the blue of every neutral value.
export function TypeBadge({ skillName }) {
  const session = !skillName
  return (
    <span style={{
      color: 'var(--accent-2)',
      fontWeight: 700,
      fontSize: 12,
    }}>{session ? 'session' : 'skill'}</span>
  )
}

// Colored label so good/bad reads at a glance - plain text, no bounding box.
function ScoreBadge({ kind }) {
  const color = kind === 'good' ? 'var(--good)' : 'var(--bad)'
  return (
    <span style={{
      color,
      fontWeight: 700,
      fontSize: 12,
    }}>{kind}</span>
  )
}

export function scoreLabel(score) {
  if (score === 1) return <ScoreBadge kind="good" />
  if (score === 2) return <ScoreBadge kind="bad" />
  return <Dash />
}
