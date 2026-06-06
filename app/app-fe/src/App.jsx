import { useCallback, useEffect, useRef, useState } from 'react'

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

  // Mirror `filter` into a ref so the WebSocket handler can read the latest
  // value without re-subscribing each time a filter is applied or cleared.
  const filterRef = useRef(false)
  useEffect(() => { filterRef.current = !!filter }, [filter])

  // Apply a fresh dataset from either the initial fetch or a live snapshot.
  // Index transcripts so each feedback row can show its own conversation inline
  // (prefer request_id 1:1, fall back to session_id). A live push refreshes the
  // visible rows only when no filter is active, so it never clobbers a filter.
  const applyData = useCallback((feedback, transcripts, topSkills) => {
    const index = {}
    for (const t of transcripts) {
      if (t.request_id) index[`r:${t.request_id}`] = t
      if (t.session_id) index[`s:${t.session_id}`] = t
    }
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
    <div style={{ padding: 24, maxWidth: 1100, margin: '0 auto', color: 'var(--text)' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <h1 style={{ margin: 0 }}>RateXp</h1>
          <LiveDot live={live} />
        </div>
        <button onClick={toggleTheme} title="Toggle light/dark">
          {theme === 'dark' ? '☀ Light' : '🌙 Dark'}
        </button>
      </div>
      {(loading || error || filter) && (
        <p style={{ color: 'var(--muted)', marginTop: 4 }}>
          <StatusLine loading={loading} error={error} filtered={!!filter} />
        </p>
      )}
      {!loading && !error && <TopSkills skills={stats} />}
      <FilterBar apiBase={API_BASE} rows={rows} active={!!filter} onFilter={applyFilter} onClear={clearFilter} />
      {!loading && !error && filter?.truncated && <ViewLimitNotice shown={rows.length} />}
      {!loading && !error && (
        <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: 14 }}>
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
                <Td>{r.created_at}</Td>
                <Td><code>{r.skill_name}</code></Td>
                <Td><code>{r.agent}</code></Td>
                <Td>{scoreLabel(r.score)}</Td>
                <Td>{r.comment ?? <Dash />}</Td>
                <Td><Conversation transcript={transcriptFor(r)} /></Td>
                <Td><code style={{ fontSize: 11 }}>{r.session_id}</code></Td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

function okJson(r) {
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return r.json()
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
    <section style={{
      margin: '8px 0 20px',
      border: '1px solid var(--glass-border)',
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
// Tells the user the view is capped and to use Download CSV (which re-runs the
// filter with full=true) to get the complete result set.
function ViewLimitNotice({ shown }) {
  return (
    <p style={{
      margin: '0 0 12px',
      padding: '10px 14px',
      border: '1px solid var(--glass-border)',
      borderRadius: 10,
      background: 'var(--glass-bg)',
      color: 'var(--muted)',
      fontSize: 13,
    }}>
      Showing the first <strong>{shown}</strong> rows — you have more than the view limit.
      To see all, use <strong>Download CSV</strong> above.
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

  // The table only shows the backend's capped "view"; Download CSV asks the
  // backend for the FULL set (full=true) so the user can "see all". For a filter
  // it re-runs the same SELECT unbounded; otherwise it exports all feedback.
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
      const csv = mainRowsToCsv(exportRows)
      const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }))
      const a = document.createElement('a')
      a.href = url
      a.download = 'ratexp-feedback.csv'
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      setErr(String(e.message || e))
    }
  }

  return (
    <section style={{
      margin: '8px 0 20px',
      border: '1px solid var(--glass-border)',
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
      <div style={{ marginTop: 8, display: 'flex', gap: 8, alignItems: 'center' }}>
        <button onClick={run} disabled={running || !sql.trim()}>{running ? 'Filtering…' : 'Apply filter'}</button>
        <button onClick={clear} disabled={!active && !sql}>Clear</button>
        <button onClick={download} disabled={rows.length === 0}>Download CSV</button>
        {err && <span style={{ color: 'var(--danger)', fontSize: 13 }}>{err}</span>}
      </div>
    </section>
  )
}

// Columns exported to CSV — the feedback table's data fields, in display order.
const CSV_COLUMNS = ['created_at', 'skill_name', 'agent', 'score', 'comment', 'session_id', 'request_id']

// Build RFC-4180-ish CSV from the table's rows: quote every field, escape quotes.
function mainRowsToCsv(rows) {
  const cell = (v) => `"${(v === null || v === undefined ? '' : String(v)).replace(/"/g, '""')}"`
  const lines = [CSV_COLUMNS.map(cell).join(',')]
  for (const r of rows) lines.push(CSV_COLUMNS.map((c) => cell(r[c])).join(','))
  return lines.join('\r\n')
}

// Each feedback row reveals its own stored conversation as a tab-like
// expander, right on the same row — no separate top-level Transcripts view.
function Conversation({ transcript }) {
  const steps = transcript?.atif?.steps ?? []
  if (steps.length === 0) return <Dash />
  return (
    <details>
      <summary style={{ cursor: 'pointer', color: 'var(--accent)' }}>View ({steps.length} steps)</summary>
      <div style={{ marginTop: 8, maxWidth: 520 }}>
        {steps.map((s, i) => (
          <div key={i} style={{ marginBottom: 8 }}>
            <span style={sourceStyle(s.source)}>{s.source}</span>
            {s.message && <div style={{ whiteSpace: 'pre-wrap' }}>{s.message}</div>}
            {Array.isArray(s.tool_calls) && s.tool_calls.length > 0 && (
              <div style={{ color: 'var(--muted)', fontSize: 12 }}>
                🔧 {s.tool_calls.map((t) => t.name).join(', ')}
              </div>
            )}
            {s.observation && (
              <div style={{ color: 'var(--faint)', fontSize: 12, whiteSpace: 'pre-wrap' }}>↳ {s.observation}</div>
            )}
          </div>
        ))}
      </div>
    </details>
  )
}

const thStyle = {
  textAlign: 'left',
  padding: '10px 12px',
  borderBottom: '1px solid var(--glass-border)',
  background: 'var(--glass-bg-strong)',
  fontSize: 12,
  textTransform: 'uppercase',
  letterSpacing: '.04em',
  color: 'var(--muted)',
}
const tdStyle = { padding: '10px 12px', borderBottom: '1px solid var(--row-border)', verticalAlign: 'top' }

function Th({ children }) { return <th style={thStyle}>{children}</th> }
function Td({ children }) { return <td style={tdStyle}>{children}</td> }
function Dash() { return <span style={{ color: 'var(--faint)' }}>—</span> }

function sourceStyle(source) {
  const color = source === 'user' ? 'var(--accent-2)' : source === 'agent' ? 'var(--good)' : 'var(--faint)'
  return { fontSize: 11, textTransform: 'uppercase', letterSpacing: '.04em', color, fontWeight: 600 }
}

// Small colored pill so good/bad reads at a glance against the dark theme.
function ScoreBadge({ kind }) {
  const color = kind === 'good' ? 'var(--good)' : 'var(--bad)'
  return (
    <span style={{
      color,
      fontWeight: 600,
      fontSize: 12,
      textTransform: 'uppercase',
      letterSpacing: '.04em',
      border: '1px solid currentColor',
      borderRadius: 999,
      padding: '2px 10px',
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
