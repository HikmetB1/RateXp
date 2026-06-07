import { useCallback, useEffect, useRef, useState } from 'react'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

// In the built image the dashboard is served from the same origin as the API,
// so VITE_API_BASE is "" and requests are relative. For local dev it defaults to
// app-be on :8001. (?? keeps an explicit empty string meaning "same origin".)
const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8001'
// Live updates come over a WebSocket, derived from the API base (http->ws). An
// empty API base means same origin, so build the ws URL from window.location.
const WS_BASE =
  import.meta.env.VITE_WS_BASE ||
  (API_BASE
    ? API_BASE.replace(/^http/i, 'ws')
    : window.location.origin.replace(/^http/i, 'ws'))

// Outer "group" frame: visually bundles the inner glass cards into two sections
// — (Filter + Feedback) and (Top skills) — so the two areas read as distinct
// groups. Children lay out in a column with even spacing (their own margins are
// zeroed, see the inner <section>s).
const groupBox = {
  display: 'flex',
  flexDirection: 'column',
  gap: 14,
  border: '1px solid var(--card-border)',
  borderRadius: 18,
  padding: 14,
  marginBottom: 20,
}

export default function App() {
  const [allRows, setAllRows] = useState([]) // full list from /feedback
  const [rows, setRows] = useState([]) // what the table shows (all, or filtered)
  const [stats, setStats] = useState([]) // top-rated skills from /stats/top-skills
  const [byKey, setByKey] = useState({})
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState(null) // { truncated } while a filter is active
  const [live, setLive] = useState(false) // true while the live WebSocket is connected
  // Theme is applied to <html data-theme> (see index.html/index.css). Default dark.
  const [theme, setTheme] = useState(() => document.documentElement.dataset.theme || 'dark')
  // Which row's transcript is shown in the slide-over conversation drawer.
  const [openTx, setOpenTx] = useState(null)

  // Mirror `filter` into a ref so the WebSocket handler can read the latest
  // value without re-subscribing each time a filter is applied or cleared.
  const filterRef = useRef(false)
  useEffect(() => { filterRef.current = !!filter }, [filter])

  // Apply a fresh dataset from either the initial fetch or a live snapshot.
  // Index transcripts so each feedback row can show its own conversation inline
  // (prefer request_id 1:1, fall back to session_id). A live push refreshes the
  // visible rows only when no filter is active, so it never clobbers a filter.
  const applyData = useCallback((feedback, transcripts, topSkills) => {
    const index = indexTranscripts(transcripts)
    setAllRows(feedback)
    setByKey(index)
    setStats(topSkills ?? [])
    if (!filterRef.current) setRows(feedback)
  }, [])

  const toggleTheme = () => {
    const next = theme === 'dark' ? 'light' : 'dark'
    setTheme(next)
    document.documentElement.dataset.theme = next
    try { localStorage.setItem('ratexp-theme', next) } catch {}
  }

  useEffect(() => {
    // Initial load over HTTP — works even if the WebSocket is blocked. No ?limit:
    // the backend returns its configured "view" size (list_view_limit), so the
    // table's row count is decided server-side, not here.
    Promise.all([
      fetch(`${API_BASE}/feedback`).then(okJson),
      fetch(`${API_BASE}/transcript`).then(okJson),
      fetch(`${API_BASE}/stats/top-skills`).then(okJson),
    ])
      .then(([feedback, transcripts, topSkills]) => {
        applyData(feedback, transcripts, topSkills.skills ?? [])
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false))
  }, [applyData])

  // Live updates: connect to /ws and apply each pushed snapshot. The backend
  // sends one on connect and again whenever the data changes. Auto-reconnects
  // with a fixed delay so a dropped connection recovers on its own.
  useEffect(() => {
    let ws
    let retry
    let stopped = false
    const connect = () => {
      try {
        ws = new WebSocket(`${WS_BASE}/ws`)
      } catch {
        return
      }
      ws.onopen = () => setLive(true)
      ws.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data)
          if (msg.type === 'snapshot') {
            applyData(msg.feedback ?? [], msg.transcripts ?? [], msg.stats ?? [])
          }
        } catch { /* ignore malformed frames */ }
      }
      ws.onclose = () => {
        setLive(false)
        if (!stopped) retry = setTimeout(connect, 3000)
      }
      ws.onerror = () => { try { ws.close() } catch {} }
    }
    connect()
    return () => {
      stopped = true
      clearTimeout(retry)
      if (ws) { ws.onclose = null; ws.close() }
    }
  }, [applyData])

  const transcriptFor = (r) => byKey[`r:${r.request_id}`] || byKey[`s:${r.session_id}`] || null

  // A filter replaces the table's rows in place; Clear restores the full list.
  const applyFilter = (resultRows, meta) => {
    setRows(resultRows)
    setFilter(meta)
  }
  const clearFilter = () => {
    setRows(allRows)
    setFilter(null)
  }

  return (
    <div className="app" style={{ color: 'var(--text)' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', marginBottom: 18 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {/* Brand mark: the logo shape is used as a CSS mask and filled with the
              same accent→accent-2 gradient as the "RateXp" wordmark, so the two
              read as one unit and recolour together with the theme. */}
          <span className="brand-logo" role="img" aria-label="RateXp logo" />
          <h1 style={{ margin: 0 }}>RateXp</h1>
          <span style={{ marginLeft: 4 }}><LiveDot live={live} /></span>
        </div>
        <button
          className="btn-edge"
          onClick={toggleTheme}
          title="Toggle light/dark"
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 6,
            whiteSpace: 'nowrap',
            minWidth: '6rem',
            padding: '9px 16px',
            lineHeight: 1.2,
          }}
        >
          <span aria-hidden="true" style={{ fontSize: 14, lineHeight: 1 }}>🌗</span>
          {theme === 'dark' ? 'Light' : 'Dark'}
        </button>
      </div>
      {(loading || error || filter) && (
        <p style={{ color: 'var(--muted)', marginTop: 4 }}>
          <StatusLine loading={loading} error={error} filtered={!!filter} />
        </p>
      )}
      <div className="glow-edge" style={groupBox}>
        <FilterBar apiBase={API_BASE} rows={rows} active={!!filter} onFilter={applyFilter} onClear={clearFilter} />
        {!loading && !error && filter?.truncated && <ViewLimitNotice shown={rows.length} />}
        {!loading && !error && (
          <section className="glow-edge" style={{
            margin: 0,
            border: '1px solid var(--card-border)',
            borderRadius: 14,
            padding: '14px 16px',
            background: 'var(--glass-bg)',
            backdropFilter: 'var(--blur)',
            WebkitBackdropFilter: 'var(--blur)',
            boxShadow: 'var(--shadow)',
          }}>
            <h2 style={{ margin: 0, color: 'var(--accent)', fontWeight: 600, fontSize: 16 }}>Feedback</h2>
            {/* Scroll wrapper: if cells can't shrink enough on a tight width, the
                table scrolls sideways inside the card instead of overflowing it. */}
            <div className="table-scroll">
            <table className="data-table" style={{ borderCollapse: 'collapse', width: '100%', fontSize: 14, marginTop: 12 }}>
              <thead>
                <tr>
                  <Th>When</Th>
                  <Th>Skill</Th>
                  <Th>Agent</Th>
                  <Th>Score</Th>
                  <Th>Comment</Th>
                  <Th>Conversation</Th>
                  <Th>Session</Th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={i}>
                    <Td label="When">{r.created_at}</Td>
                    <Td label="Skill"><code>{r.skill_name}</code></Td>
                    <Td label="Agent"><code>{r.agent}</code></Td>
                    <Td label="Score">{scoreLabel(r.score)}</Td>
                    <Td label="Comment">{r.comment ?? <Dash />}</Td>
                    <Td label="Conversation"><Conversation transcript={transcriptFor(r)} onOpen={(t) => setOpenTx({ transcript: t, row: r })} /></Td>
                    <Td label="Session"><code style={{ fontSize: 11 }}>{r.session_id}</code></Td>
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
            {!filter && <ViewDisclaimer />}
          </section>
        )}
      </div>
      {!loading && !error && (
        <div className="glow-edge" style={groupBox}>
          <TopSkills skills={stats} />
        </div>
      )}
      <ConversationDrawer data={openTx} onClose={() => setOpenTx(null)} />
    </div>
  )
}

// Always-on note under the default table: the dashboard is a preview that shows
// only the latest rows and the most-rated skills (both capped by app-be's
// config.yaml — list_view_limit / top_skills_limit, default 10 each). The data
// behind it is larger; Download JSON or the SQL box pull the full set (up to
// query_max_rows). Hidden while a filter is active, since ViewLimitNotice then
// explains the cap for the filtered result instead.
function ViewDisclaimer() {
  return (
    <p style={{
      margin: '12px 0 0',
      color: 'var(--danger)',
      fontWeight: 700,
      fontSize: 13,
      textAlign: 'center',
    }}>
      This is a preview — the table shows only the latest entries and the “Top skills”
      panel only the most-rated skills. Use <strong>Download JSON</strong> or the SQL
      filter above to get the full data.
    </p>
  )
}

function okJson(r) {
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return r.json()
}

// Index transcripts by request_id (1:1) and session_id (fallback) so a feedback
// row can find its conversation. Used both for the live table and CSV export.
function indexTranscripts(transcripts) {
  const index = {}
  for (const t of transcripts) {
    if (t.request_id) index[`r:${t.request_id}`] = t
    if (t.session_id) index[`s:${t.session_id}`] = t
  }
  return index
}

// Small dot showing whether the live WebSocket is connected. Green + glowing
// when updates are streaming in; grey when offline (the table still works from
// the initial load and reconnects on its own).
function LiveDot({ live }) {
  return (
    <span
      title={live ? 'Live — updating in real time' : 'Offline — not receiving live updates'}
      style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--muted)' }}
    >
      <span style={{
        width: 8,
        height: 8,
        borderRadius: 999,
        background: live ? 'var(--good)' : 'var(--faint)',
        boxShadow: live ? '0 0 6px var(--good)' : 'none',
      }} />
      {live ? 'Live' : 'Offline'}
    </span>
  )
}

// Always-on stats panel: the most-rated skills and their good/bad score,
// aggregated across the whole feedback table by GET /stats/top-skills. How many
// it returns is set by top_skills_limit in app-be's config.yaml (default 10).
function TopSkills({ skills }) {
  if (!skills || skills.length === 0) return null
  return (
    <section className="glow-edge" style={{
      margin: 0,
      border: '1px solid var(--card-border)',
      borderRadius: 14,
      padding: '14px 16px',
      background: 'var(--glass-bg)',
      backdropFilter: 'var(--blur)',
      WebkitBackdropFilter: 'var(--blur)',
      boxShadow: 'var(--shadow)',
    }}>
      <h2 style={{ margin: 0, color: 'var(--accent)', fontWeight: 600, fontSize: 16 }}>Top skills</h2>
      <p style={{ color: 'var(--muted)', fontSize: 13, marginTop: 8, marginBottom: 12 }}>
        The {skills.length} most-rated skill{skills.length === 1 ? '' : 's'} and their score across all feedback.
      </p>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {skills.map((s, i) => {
          const ratio = s.total > 0 ? s.good / s.total : 0
          return (
            <div key={i} style={{ display: 'grid', gridTemplateColumns: '24px 1fr auto', gap: 12, alignItems: 'center' }}>
              <span style={{ color: 'var(--faint)', fontSize: 13, textAlign: 'right' }}>{i + 1}</span>
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, marginBottom: 4 }}>
                  <code>{s.skill_name}</code>
                  <span style={{ color: 'var(--muted)' }}>{s.total} rating{s.total === 1 ? '' : 's'}</span>
                </div>
                {/* Good/bad split bar: green portion is good, red is bad. */}
                <div style={{ height: 8, borderRadius: 999, overflow: 'hidden', display: 'flex', background: 'var(--row-border)' }}>
                  <div style={{ width: `${ratio * 100}%`, background: 'var(--good)' }} />
                  <div style={{ width: `${(s.total > 0 ? s.bad / s.total : 0) * 100}%`, background: 'var(--bad)' }} />
                </div>
              </div>
              <span style={{ fontSize: 12, color: 'var(--muted)', whiteSpace: 'nowrap' }}>
                <span style={{ color: 'var(--good)', fontWeight: 600 }}>{s.good}</span>
                {' / '}
                <span style={{ color: 'var(--bad)', fontWeight: 600 }}>{s.bad}</span>
              </span>
            </div>
          )
        })}
      </div>
    </section>
  )
}

// Shown when a filter has more matches than the backend's view size returned.
// Tells the user the view is capped and to use Download JSON (which re-runs the
// filter with full=true) to get the complete result set.
function ViewLimitNotice({ shown }) {
  return (
    <p style={{
      margin: '0 0 12px',
      padding: '10px 14px',
      border: '1px solid var(--card-border)',
      borderRadius: 10,
      background: 'var(--glass-bg)',
      color: 'var(--muted)',
      fontSize: 13,
    }}>
      Showing the first <strong>{shown}</strong> rows — you have more than the view limit.
      To see all, use <strong>Download JSON</strong> above.
    </p>
  )
}

const EXAMPLE_SQL = 'SELECT * FROM feedback WHERE score = 2'

// SELECT-only SQL box that filters the feedback table below in place: the query
// result replaces the table's rows (Clear restores the full list). The backend
// enforces all the guardrails (SELECT-only, read-only, timeout, row cap).
function FilterBar({ apiBase, rows, active, onFilter, onClear }) {
  const [sql, setSql] = useState('')
  const [err, setErr] = useState(null)
  const [running, setRunning] = useState(false)

  const run = () => {
    setRunning(true)
    setErr(null)
    fetch(`${apiBase}/query`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ sql }),
    })
      .then(async (r) => {
        const body = await r.json().catch(() => ({}))
        if (!r.ok) throw new Error(body.detail || `HTTP ${r.status}`)
        return body
      })
      .then((body) => onFilter(body.rows, { truncated: body.truncated }))
      .catch((e) => setErr(String(e.message || e)))
      .finally(() => setRunning(false))
  }

  const clear = () => {
    setSql('')
    setErr(null)
    onClear()
  }

  // The table only shows the backend's capped "view"; Download JSON asks the
  // backend for the FULL set (full=true) so the user can "see all". For a filter
  // it re-runs the same SELECT unbounded; otherwise it exports all feedback.
  // Each row carries its full ATIF trajectory (the native JSON shape) under
  // `conversation`, so the export keeps the whole transcript — steps, tool calls
  // and metrics — instead of flattening it the way a CSV cell would.
  const download = async () => {
    setErr(null)
    try {
      let exportRows
      if (active && sql.trim()) {
        const r = await fetch(`${apiBase}/query`, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ sql, full: true }),
        })
        const body = await r.json().catch(() => ({}))
        if (!r.ok) throw new Error(body.detail || `HTTP ${r.status}`)
        exportRows = body.rows
      } else {
        exportRows = await fetch(`${apiBase}/feedback?full=true`).then(okJson)
      }
      // Match each exported row to its stored conversation (request_id, then
      // session_id) and attach the full ATIF transcript.
      const index = indexTranscripts(await fetch(`${apiBase}/transcript?full=true`).then(okJson))
      const exportWithConversation = exportRows.map((r) => {
        const transcript = index[`r:${r.request_id}`] || index[`s:${r.session_id}`]
        return { ...r, conversation: transcript?.atif ?? null }
      })
      const json = JSON.stringify(exportWithConversation, null, 2)
      const url = URL.createObjectURL(new Blob([json], { type: 'application/json;charset=utf-8' }))
      const a = document.createElement('a')
      a.href = url
      a.download = 'ratexp-feedback.json'
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      setErr(String(e.message || e))
    }
  }

  return (
    <section className="glow-edge" style={{
      margin: 0,
      border: '1px solid var(--card-border)',
      borderRadius: 14,
      padding: '14px 16px',
      background: 'var(--glass-bg)',
      backdropFilter: 'var(--blur)',
      WebkitBackdropFilter: 'var(--blur)',
      boxShadow: 'var(--shadow)',
    }}>
      <h2 style={{ margin: 0, color: 'var(--accent)', fontWeight: 600, fontSize: 16 }}>Filter with SQL</h2>
      <p style={{ color: 'var(--muted)', fontSize: 13, marginTop: 8 }}>
        Read-only SELECT against the feedback table — results replace the table below.
        Tip: <code>SELECT * FROM feedback WHERE …</code>. Results are capped and time-limited.
      </p>
      <textarea
        value={sql}
        onChange={(e) => setSql(e.target.value)}
        placeholder={EXAMPLE_SQL}
        rows={3}
        spellCheck={false}
        style={{ width: '100%', fontFamily: "'JetBrains Mono', monospace", fontSize: 13, padding: 10, boxSizing: 'border-box' }}
      />
      <div style={{ marginTop: 8, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <button className="btn-edge" onClick={run} disabled={running || !sql.trim()}>{running ? 'Filtering…' : 'Apply filter'}</button>
        <button className="btn-edge" onClick={clear} disabled={!active && !sql}>Clear</button>
        <button className="btn-edge" onClick={download} disabled={rows.length === 0}>Download JSON</button>
        {err && <span style={{ color: 'var(--danger)', fontSize: 13 }}>{err}</span>}
      </div>
    </section>
  )
}

// Each feedback row links to its stored conversation; opening it reveals the
// full trajectory in a slide-over drawer (see ConversationDrawer) rather than
// cramming it into the table cell.
function Conversation({ transcript, onOpen }) {
  const steps = transcript?.atif?.steps ?? []
  if (steps.length === 0) return <Dash />
  return (
    <button
      className="tx-chip"
      onClick={() => onOpen(transcript)}
      title={`Open conversation — ${steps.length} steps`}
    >
      {/* Line-style chat glyph — echoes the timeline in the drawer this opens. */}
      <svg className="tx-chip-ico" viewBox="0 0 16 16" width="13" height="13" aria-hidden="true">
        <path
          d="M3 2.8h10a1.6 1.6 0 0 1 1.6 1.6v5.2a1.6 1.6 0 0 1-1.6 1.6H7l-3 2.8v-2.8H3a1.6 1.6 0 0 1-1.6-1.6V4.4A1.6 1.6 0 0 1 3 2.8Z"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.3"
          strokeLinejoin="round"
        />
      </svg>
      <span className="tx-chip-count">{steps.length}</span>
      <span className="tx-chip-label">steps</span>
      <span className="tx-chip-arrow" aria-hidden="true">→</span>
    </button>
  )
}

// A single agent tool call: a monospace chip showing the tool name, expandable
// to its JSON arguments when there are any.
function ToolCall({ call }) {
  const args =
    call.arguments && Object.keys(call.arguments).length > 0
      ? JSON.stringify(call.arguments, null, 2)
      : null
  if (!args) return <div className="tl-tool">⌗ {call.name}</div>
  return (
    <details className="tl-tool">
      <summary>⌗ {call.name}</summary>
      <pre className="tl-tool-args">{args}</pre>
    </details>
  )
}

// Slide-over panel showing one stored conversation as a vertical timeline:
// role-coloured dots on a connector rail, Markdown messages, collapsible tool
// calls / reasoning / observations, and a token-metrics footer. Closes on the
// backdrop, the ✕, or Escape. Rendered once at the app root; `data` carries the
// chosen transcript (and its feedback row, for the header) or null when hidden.
function ConversationDrawer({ data, onClose }) {
  useEffect(() => {
    if (!data) return
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [data, onClose])

  if (!data) return null
  const { transcript, row } = data
  const atif = transcript?.atif ?? {}
  const steps = atif.steps ?? []
  const fm = atif.final_metrics ?? {}
  const model = atif.agent?.model_name

  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-label="Conversation">
        <header className="drawer-head">
          <div>
            <div className="drawer-title">Conversation</div>
            <div className="drawer-sub">
              <code>{row?.skill_name}</code>{model ? ` · ${model}` : ''}
            </div>
          </div>
          <button className="drawer-close" onClick={onClose} aria-label="Close">✕</button>
        </header>

        <div className="drawer-body">
          <ol className="timeline">
            {steps.map((s, i) => (
              <li key={i} className="tl-step" style={{ animationDelay: `${Math.min(i * 40, 400)}ms` }}>
                <span className={`tl-dot tl-${s.source}`} />
                <div className={`tl-card tl-card-${s.source}`}>
                  <div className="tl-role" style={sourceStyle(s.source)}>{s.source}</div>
                  {s.reasoning_content && (
                    <details className="tl-reason">
                      <summary>reasoning</summary>
                      <Md className="md md-muted">{s.reasoning_content}</Md>
                    </details>
                  )}
                  {s.message && <Md className="md">{s.message}</Md>}
                  {Array.isArray(s.tool_calls) &&
                    s.tool_calls.map((t, j) => <ToolCall key={j} call={t} />)}
                  {s.observation && (
                    <details className="tl-obs">
                      <summary>↳ output</summary>
                      <Md className="md md-muted">{s.observation}</Md>
                    </details>
                  )}
                </div>
              </li>
            ))}
          </ol>
        </div>

        <footer className="drawer-foot">
          <span>{fm.total_steps ?? steps.length} steps</span>
          <span>↑ {fm.total_prompt_tokens ?? 0} · ↓ {fm.total_completion_tokens ?? 0} tok</span>
        </footer>
      </aside>
    </>
  )
}

// Render an ATIF step's text (agent/user messages, tool observations) as
// Markdown — agents write Markdown (headings, lists, code blocks, tables), so
// rendering it formatted is what makes the transcript readable. GFM adds tables,
// task lists and strikethrough. Styling lives under the .md class in index.css.
// (react-markdown v9 has no className prop, so we wrap it in a div.)
function Md({ className, children }) {
  return (
    <div className={className}>
      <Markdown remarkPlugins={[remarkGfm]}>{String(children ?? '')}</Markdown>
    </div>
  )
}

// Cell styling lives in index.css (.th/.td) so the mobile breakpoint can
// restyle the table into stacked cards — inline styles would block those rules.
// Each Td carries a `label` echoed into data-label, used as the card row's
// heading on phones (see the @media block in index.css).
function Th({ children }) { return <th className="th">{children}</th> }
function Td({ children, label }) { return <td className="td" data-label={label}>{children}</td> }
function Dash() { return <span style={{ color: 'var(--faint)' }}>—</span> }

function sourceStyle(source) {
  const color = source === 'user' ? 'var(--accent-2)' : source === 'agent' ? 'var(--good)' : 'var(--faint)'
  return { fontSize: 11, textTransform: 'uppercase', letterSpacing: '.04em', color, fontWeight: 600 }
}

// Colored label so good/bad reads at a glance — plain text, no bounding box.
function ScoreBadge({ kind }) {
  const color = kind === 'good' ? 'var(--good)' : 'var(--bad)'
  return (
    <span style={{
      color,
      fontWeight: 700,
      fontSize: 12,
      textTransform: 'uppercase',
      letterSpacing: '.04em',
    }}>{kind}</span>
  )
}

function scoreLabel(score) {
  if (score === 1) return <ScoreBadge kind="good" />
  if (score === 2) return <ScoreBadge kind="bad" />
  return <Dash />
}

function StatusLine({ loading, error, filtered }) {
  if (loading) return 'Loading…'
  if (error) return <span style={{ color: 'var(--danger)' }}>{error}</span>
  if (filtered) return 'Filtered'
  return null
}
