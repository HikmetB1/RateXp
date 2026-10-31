import { useEffect, useRef, useState } from 'react'
import { FeedbackTable } from './FeedbackTable.jsx'
import { cardHeading, glassCard, groupBox } from './styles.js'

// The Dashboard view: filters + one panel per entry the API lists under GET /dashboard.
// Each panel's rows come from POST /dashboard/panel and are drawn by their `kind`; the one
// table is the Feedback table of the Query & table view.

// Time-range buttons; "All" sends no lower bound. 30d is the default because the Dynatrace
// dashboard opens on the same window, so both show the same numbers.
const RANGES = [
  { key: '24h', label: '24h', ms: 24 * 3600e3 },
  { key: '7d', label: '7d', ms: 7 * 24 * 3600e3 },
  { key: '30d', label: '30d', ms: 30 * 24 * 3600e3 },
  { key: 'all', label: 'All', ms: null },
]
const DEFAULT_RANGE = '30d'
// Type first: skill or session, where a session rating is one that has no skill. Picking
// one narrows every other dropdown to the values that exist for it. The last three are the
// labels core gives a stored conversation; a rating takes its conversation's.
const FILTER_KEYS = ['type', 'skill', 'agent', 'eval', 'business_case', 'language', 'task_type']
const NO_FILTERS = Object.fromEntries(FILTER_KEYS.map((key) => [key, null]))
const DAY_MS = 24 * 3600e3

const PANEL_CLASS = { number: 'panel-number', line: 'panel-line', bar: 'panel-bar', table: 'panel-table' }
// The panels about skills, which a session rating has none of.
const SKILL_PANELS = new Set(['skills_rated', 'percent_good_by_skill'])

// Computed at fetch time, so a live refresh moves the window along with the clock.
function sinceFor(rangeKey) {
  const ms = RANGES.find((r) => r.key === rangeKey).ms
  return ms ? new Date(Date.now() - ms).toISOString() : null
}

// The API's JSON answer. A failed call throws the API's own `detail` (the database error,
// say), so the view shows why instead of a bare status code.
async function fetchJson(url, init) {
  const r = await fetch(url, init)
  const body = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(body.detail || `HTTP ${r.status}`)
  return body
}

function fetchPanel(apiBase, panel, filters) {
  return fetchJson(`${apiBase}/dashboard/panel`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ panel, filters }),
  })
}

// Picks the type's dropdowns no longer list go back to all. The same object when none do,
// so the panels are not asked again for nothing.
function keepListedPicks(filters, values) {
  const dropped = FILTER_KEYS.filter((key) => key !== 'type' && filters[key] != null && !(values[key] ?? []).includes(filters[key]))
  return dropped.length ? { ...filters, ...Object.fromEntries(dropped.map((key) => [key, null])) } : filters
}

// `active` is false while the view is hidden behind the other one: it then asks the API
// nothing, and refreshes once when shown again. `onOpenTrajectory(transcript, row)` opens a
// Feedback row's trajectory in the app's drawer.
export default function Dashboard({ apiBase, liveTick, active, onOpenTrajectory }) {
  const [info, setInfo] = useState(null) // GET /dashboard: availability, dropdown values, panel list, download limit
  const [infoError, setInfoError] = useState(null)
  const [filters, setFilters] = useState(NO_FILTERS)
  const [range, setRange] = useState(DEFAULT_RANGE)
  const [results, setResults] = useState({}) // panel id -> {columns, rows} | {error}
  const [updating, setUpdating] = useState(false)
  const [exportError, setExportError] = useState(null)
  // Answers from a batch started before the latest filter change are dropped, so a slow
  // old query cannot overwrite a fresh panel - and the same for the dropdown values.
  const batch = useRef(0)
  const valuesBatch = useRef(0)

  // GET /dashboard again on each type pick, each live snapshot and each time the view is
  // shown again: that narrows the dropdowns to the picked type, retries a failed load, and a
  // skill, agent or eval rated for the first time joins the dropdowns. The picked filters
  // are their own state, so they survive the refresh, but for a pick the type has no
  // ratings for; a failed refresh leaves the last answer on screen.
  useEffect(() => {
    if (!active) return
    const id = ++valuesBatch.current
    const query = filters.type ? `?${new URLSearchParams({ type: filters.type })}` : ''
    fetchJson(`${apiBase}/dashboard${query}`)
      .then((d) => {
        if (id !== valuesBatch.current) return
        setInfo(d)
        setInfoError(null)
        if (d.available) setFilters((f) => keepListedPicks(f, d.filters ?? {}))
      })
      .catch((e) => {
        if (id === valuesBatch.current) setInfoError(String(e.message || e))
      })
  }, [apiBase, liveTick, active, filters.type])

  // Fetch every panel when shown, on each filter change and on each live snapshot (liveTick).
  // Keyed on the panel ids rather than on `info`, which the refresh above replaces on every
  // snapshot and would start a second batch. The old panels stay on screen until the fresh
  // ones land, so nothing flickers.
  const panelIds = info?.available ? info.panels.map((p) => p.id).join(' ') : ''
  useEffect(() => {
    if (!active || !panelIds) return
    const id = ++batch.current
    const body = { ...filters, since: sinceFor(range) }
    setUpdating(true)
    Promise.all(
      panelIds.split(' ').map((panel) =>
        fetchPanel(apiBase, panel, body)
          .catch((e) => ({ error: String(e.message || e) }))
          .then((result) => {
            if (id === batch.current) setResults((prev) => ({ ...prev, [panel]: result }))
          }),
      ),
    ).finally(() => {
      if (id === batch.current) setUpdating(false)
    })
  }, [apiBase, panelIds, filters, range, liveTick, active])

  // Save the newest ratings matching the filters, up to the API's download_limit, each with
  // its conversation, as one JSON file. Absent filters are left out of the URL so the API
  // reads them as "all".
  const download = async () => {
    setExportError(null)
    try {
      const query = new URLSearchParams()
      for (const [k, v] of Object.entries({ ...filters, since: sinceFor(range) })) if (v) query.set(k, v)
      const rows = await fetchJson(`${apiBase}/dashboard/export?${query}`)
      const url = URL.createObjectURL(new Blob([JSON.stringify(rows, null, 2)], { type: 'application/json;charset=utf-8' }))
      const a = document.createElement('a')
      a.href = url
      a.download = 'ratexp-feedback.json'
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      setExportError(String(e.message || e))
    }
  }

  // A session rating has no skill, so picking session also drops a picked skill.
  const pick = (key, value) =>
    setFilters((f) => ({ ...f, [key]: value, ...(key === 'type' && value === 'session' ? { skill: null } : {}) }))

  if (!info) {
    return (
      <p style={{ color: 'var(--muted)', marginTop: 4 }}>
        {infoError ? <span style={{ color: 'var(--danger)' }}>{infoError}</span> : 'Loading...'}
      </p>
    )
  }
  if (!info.available) {
    return (
      <div className="glow-edge" style={groupBox}>
        <section className="glow-edge" style={glassCard}>
          <h2 style={cardHeading}>Dashboard</h2>
          <Muted style={{ marginTop: 12 }}>{info.reason}</Muted>
        </section>
      </div>
    )
  }
  return (
    <div className="glow-edge" style={groupBox}>
      <FilterCard
        values={info.filters ?? {}}
        filters={filters}
        onPick={pick}
        range={range}
        onRange={setRange}
        updating={updating && Object.keys(results).length > 0}
        onDownload={download}
        downloadLimit={info.download_limit}
        downloadError={exportError}
      />
      <div className="dashboard-grid">
        {info.panels.map((p) => (
          <Panel key={p.id} panel={p} result={results[p.id]} type={filters.type} onOpenTrajectory={onOpenTrajectory} />
        ))}
      </div>
    </div>
  )
}

// Session hides the Skill dropdown: the type has no skills to pick.
function FilterCard({ values, filters, onPick, range, onRange, updating, onDownload, downloadLimit, downloadError }) {
  return (
    <section className="glow-edge" style={glassCard}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <h2 style={cardHeading}>Filters</h2>
        {updating && <span className="dashboard-label">updating...</span>}
      </div>
      <div style={{ display: 'flex', alignItems: 'flex-end', gap: 12, flexWrap: 'wrap', marginTop: 14 }}>
        {FILTER_KEYS.filter((key) => !(key === 'skill' && filters.type === 'session')).map((key) => (
          <label key={key} className="dashboard-field">
            <span className="dashboard-label">{key.replace('_', ' ')}</span>
            <select
              className="dashboard-select"
              value={filters[key] ?? ''}
              onChange={(e) => onPick(key, e.target.value || null)}
            >
              <option value="">All</option>
              {(values[key] ?? []).filter(Boolean).map((v) => <option key={v} value={v}>{v}</option>)}
            </select>
          </label>
        ))}
        {/* They look like the view tabs but pick a value instead of showing a panel, so
            screen readers hear toggle buttons, not tabs. */}
        <div role="group" aria-label="Time range" style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {RANGES.map((r) => (
            <button
              key={r.key}
              aria-pressed={r.key === range}
              className="btn-edge"
              onClick={() => onRange(r.key)}
              style={{ padding: '7px 14px', lineHeight: 1.2, opacity: r.key === range ? 1 : 0.55 }}
            >
              {r.label}
            </button>
          ))}
        </div>
        <button
          className="btn-edge"
          onClick={onDownload}
          style={{ marginLeft: 'auto' }}
          title={`The newest ${downloadLimit} ratings that match the filters, each with its conversation, as JSON`}
        >
          Download trajectories
        </button>
      </div>
      {downloadError && <p style={{ color: 'var(--danger)', fontSize: 13, margin: '10px 0 0' }}>{downloadError}</p>}
    </section>
  )
}

// One card per panel. Number tiles are a quarter wide, so their heading shrinks to fit.
// Long titles wrap in narrow cards, and the pixel font's lines touch without the extra height.
// With type session, the skill panels stay and say on top that they do not apply.
function Panel({ panel, result, type, onOpenTrajectory }) {
  const small = panel.kind === 'number'
  const heading = { ...cardHeading, lineHeight: 1.6 }
  return (
    <section className={`glow-edge ${PANEL_CLASS[panel.kind] ?? PANEL_CLASS.table}`} style={small ? { ...glassCard, padding: '14px 16px' } : glassCard}>
      <h2 style={small ? { ...heading, fontSize: 9, padding: '5px 8px' } : heading}>{panel.title}</h2>
      {type === 'session' && SKILL_PANELS.has(panel.id) && (
        <p style={{ color: 'var(--danger)', fontWeight: 700, fontSize: small ? 12 : 13, margin: '10px 0 0' }}>
          Does not apply: the type is session, not skill.
        </p>
      )}
      <div style={{ marginTop: 12 }}>
        <PanelBody panel={panel} result={result} onOpenTrajectory={onOpenTrajectory} />
      </div>
    </section>
  )
}

function PanelBody({ panel, result, onOpenTrajectory }) {
  if (!result) return <Muted>Loading...</Muted>
  if (result.error) return <span style={{ color: 'var(--danger)', fontSize: 13 }}>{result.error}</span>
  const rows = result.rows.map((r) => Object.fromEntries(result.columns.map((c, i) => [c, r[i]])))
  switch (panel.kind) {
    case 'number':
      // Every number panel returns a bare `value`; only the share of good ratings is a percentage.
      return <BigNumber value={rows[0]?.value} suffix={panel.id === 'percent_good' ? '%' : ''} />
    case 'line':
      // Stacked bars, not lines: good and bad stack into the day's total.
      return <StackedBars rows={rows} />
    case 'bar':
      return <PercentBars rows={rows} />
    default:
      return <FeedbackRows rows={rows} onOpen={onOpenTrajectory} />
  }
}

function BigNumber({ value, suffix }) {
  return (
    <div style={{ fontFamily: "'Press Start 2P', monospace", fontSize: 26, lineHeight: 1.2, color: 'var(--text)', overflowWrap: 'anywhere' }}>
      {value == null ? <Dash /> : `${value}${suffix}`}
    </div>
  )
}

// Every day from the first rated one to the last, zero on days nobody rated, so the bars
// sit on a real time axis. The SQL buckets by UTC day; a date-only string parses as UTC
// midnight and toISOString prints UTC, so the browser's time zone never shifts a label.
function ratingsPerDay(rows) {
  const byDate = new Map(rows.map((r) => [String(r.day).slice(0, 10), r]))
  const dates = [...byDate.keys()].sort()
  const days = []
  if (dates.length === 0) return days
  const last = Date.parse(dates.at(-1))
  for (let t = Date.parse(dates[0]); t <= last; t += DAY_MS) {
    const date = new Date(t).toISOString().slice(0, 10)
    const r = byDate.get(date)
    days.push({ day: date.slice(5), good: Number(r?.good) || 0, bad: Number(r?.bad) || 0 })
  }
  return days
}

// Good (bottom) and bad (top) ratings stacked per day. Drawn in real pixels from the
// card's measured width, so the labels stay readable instead of scaling with the SVG.
function StackedBars({ rows }) {
  const ref = useRef(null)
  const width = useWidth(ref)
  const height = 220
  const pad = { top: 10, right: 10, bottom: 26, left: 34 }
  const data = ratingsPerDay(rows)
  const yMax = Math.max(1, ...data.map((d) => d.good + d.bad))
  const plotW = Math.max(0, width - pad.left - pad.right)
  const plotH = height - pad.top - pad.bottom
  const slot = data.length ? plotW / data.length : 0
  const barW = Math.max(2, slot * 0.7)
  const labelEvery = Math.ceil(data.length / Math.max(1, Math.floor(plotW / 56))) // ~56px per label
  const y = (v) => pad.top + plotH - (v / yMax) * plotH
  return (
    <div ref={ref}>
      {data.length === 0 ? <Muted>No ratings in this range</Muted> : (
        <>
          <div style={{ display: 'flex', gap: 14, fontSize: 12, color: 'var(--muted)', marginBottom: 8 }}>
            {[['good', 'var(--good)'], ['bad', 'var(--bad)']].map(([label, color]) => (
              <span key={label} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                <span style={{ width: 10, height: 10, background: color, border: '2px solid var(--ink)' }} />
                {label}
              </span>
            ))}
          </div>
          {width > 0 && (
            <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Good and bad ratings per day" style={{ display: 'block' }}>
              <line x1={pad.left} y1={pad.top} x2={pad.left} y2={pad.top + plotH} stroke="var(--ink)" strokeWidth="2" />
              <line x1={pad.left} y1={pad.top + plotH} x2={width - pad.right} y2={pad.top + plotH} stroke="var(--ink)" strokeWidth="2" />
              <text x={pad.left - 6} y={pad.top + 4} textAnchor="end" className="chart-label">{yMax}</text>
              <text x={pad.left - 6} y={pad.top + plotH} textAnchor="end" className="chart-label">0</text>
              {data.map((d, i) => {
                const x = pad.left + i * slot + (slot - barW) / 2
                return (
                  <g key={i}>
                    <title>{`${d.day}: ${d.good} good, ${d.bad} bad`}</title>
                    {d.good > 0 && <rect x={x} y={y(d.good)} width={barW} height={(d.good / yMax) * plotH} fill="var(--good)" stroke="var(--ink)" />}
                    {d.bad > 0 && <rect x={x} y={y(d.good + d.bad)} width={barW} height={(d.bad / yMax) * plotH} fill="var(--bad)" stroke="var(--ink)" />}
                    {i % labelEvery === 0 && <text x={x + barW / 2} y={height - 8} textAnchor="middle" className="chart-label">{d.day}</text>}
                  </g>
                )
              })}
            </svg>
          )}
        </>
      )}
    </div>
  )
}

// One row per name, every name the panel returns, worst first: the name and "81% · 13/16"
// on top, a track filled to percent_good below. Past about 5 rows the list scrolls inside
// the card (.bar-scroll).
function PercentBars({ rows }) {
  if (rows.length === 0) return <Muted>No rated feedback in this range</Muted>
  return (
    <div className="bar-scroll" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      {rows.map((r, i) => {
        const pct = Math.max(0, Math.min(100, Number(r.percent_good) || 0))
        return (
          <div key={i} style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) auto', gap: 8, alignItems: 'center', fontSize: 13 }}>
            {/* justifySelf: a grid item stretches by default, which drew the name chip as an empty bar. */}
            <code title={r.name} style={{ justifySelf: 'start', maxWidth: '100%', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.name}</code>
            <span style={{ color: 'var(--muted)', whiteSpace: 'nowrap' }}>
              {r.percent_good}% · <span style={{ color: 'var(--good)', fontWeight: 600 }}>{r.good}</span>/{r.total}
            </span>
            <div style={{ gridColumn: '1 / -1', height: 12, border: '2px solid var(--ink)', background: 'var(--panel2)' }}>
              <div style={{ width: `${pct}%`, height: '100%', background: 'var(--good)' }} />
            </div>
          </div>
        )
      })}
    </div>
  )
}

// The newest ratings that match the filters, in the Query & table view's Feedback table.
function FeedbackRows({ rows, onOpen }) {
  if (rows.length === 0) return <Muted>No ratings in this range</Muted>
  return <FeedbackTable rows={rows} transcriptFor={conversationOf} onOpen={onOpen} />
}

// A row's stored conversation, which the feedback panel returns beside it: the trajectory
// (atif, null when none was stored) and its labels.
function conversationOf(r) {
  if (r.atif == null) return undefined
  return { request_id: r.request_id, atif: r.atif, business_case: r.business_case, language: r.language, task_type: r.task_type }
}

// Width of the element, kept current as the card resizes (a hidden view measures 0 and
// fills in once shown).
function useWidth(ref) {
  const [width, setWidth] = useState(0)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const update = () => setWidth(el.clientWidth)
    update()
    const observer = new ResizeObserver(update)
    observer.observe(el)
    return () => observer.disconnect()
  }, [ref])
  return width
}

function Muted({ children, style }) {
  return <p style={{ color: 'var(--muted)', fontSize: 13, margin: 0, ...style }}>{children}</p>
}
function Dash() { return <span style={{ color: 'var(--faint)' }}>—</span> }
