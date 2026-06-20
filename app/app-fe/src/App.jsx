import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

// Same origin as the API in the built image (VITE_API_BASE ""); defaults to app-be on :8001 in dev.
const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8001'
// WebSocket base derived from the API base (http->ws); same origin if the API base is empty.
const WS_BASE =
  import.meta.env.VITE_WS_BASE ||
  (API_BASE
    ? API_BASE.replace(/^http/i, 'ws')
    : window.location.origin.replace(/^http/i, 'ws'))

// Core MCP endpoint shown in the "Add your skill" popup. Update if the core URL changes.
const CORE_MCP_URL = 'https://ratexp-dev-core.azurewebsites.net/mcp'

// How-to shown in the "Add your skill" popup, rendered as Markdown (see Md).
const SKILL_GUIDE_MD = `### Add RateXp to your skill

RateXp runs over **MCP** - two small files, no scripts to install.

**1.** Add a \`.mcp.json\` at your **project root** pointing at this core:

\`\`\`json
{
  "mcpServers": {
    "ratexp": { "type": "http", "url": "${CORE_MCP_URL}" }
  }
}
\`\`\`

**2.** In your **\`SKILL.md\`**, add a Feedback step where feedback should take place:

\`\`\`md
## Feedback step

Call the \`feedback\` tool on the **ratexp** MCP server with \`every: 1\`, then
follow the instructions it returns.
\`\`\`

\`every: 1\` asks every time; raise the number to ask less often.

---

🎉 **Congratulations!** Your skill is now exposed to RateXp. Under the user
consent, every N run can collect a good / bad rating and its full trajectory.`

// Shown in the "preview & download" info popup (the (i) badge and the "click here for
// more details" links), rendered as Markdown (see Md).
const DOWNLOAD_INFO_MD = `### Preview & downloads

The dashboard updates in **real time**, but the table only shows the **most recent
entries** so it stays fast and smooth. To get more than the preview, use the SQL
filter or **Download JSON**.

**What Download JSON gives you**

- **No query** - just the **10 most recent** entries.
- **A query for a single skill** - **all** entries for that skill.
- **A query covering more than one skill** - only the **10 most recent**.

**To get everything for your skill**, query that one skill, then click Download JSON:

\`\`\`sql
SELECT * FROM feedback WHERE skill_name = 'your-skill'
\`\`\``

// Outer frame bundling the inner cards into one section (the chunky "big box").
const groupBox = {
  display: 'flex',
  flexDirection: 'column',
  gap: 14,
  border: '4px solid var(--ink)',
  padding: 14,
  marginBottom: 24,
  background: 'var(--box)',
  boxShadow: '5px 5px 0 var(--ink)',
}

// The inner card each section sits in. Shared so the cards stay identical.
const glassCard = {
  margin: 0,
  border: '4px solid var(--ink)',
  padding: '18px 20px',
  background: 'var(--panel)',
  boxShadow: '5px 5px 0 var(--ink)',
}

// Heading shared by all three cards: a pixel-font block in the button colour.
const cardHeading = {
  margin: 0,
  display: 'inline-block',
  fontFamily: "'Press Start 2P', monospace",
  fontSize: 13,
  color: 'var(--btnfg)',
  background: 'var(--btn)',
  padding: '7px 11px',
  border: '3px solid var(--ink)',
  boxShadow: '3px 3px 0 var(--box)',
}

export default function App() {
  const [allRows, setAllRows] = useState([]) // full list from /feedback
  const [rows, setRows] = useState([]) // what the table shows (all, or filtered)
  const [stats, setStats] = useState([]) // top-rated skills from /stats/top-skills
  const [byKey, setByKey] = useState({}) // transcripts for the live preview rows
  const [filterByKey, setFilterByKey] = useState({}) // transcripts for the filtered rows
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState(null) // { truncated } while a filter is active
  const [live, setLive] = useState(false) // true while the live WebSocket is connected
  const [liveTick, setLiveTick] = useState(0) // bumped on every live snapshot, to re-run an active filter
  // Theme is applied to <html data-theme> (see index.html/index.css). Default dark.
  const [theme, setTheme] = useState(() => document.documentElement.dataset.theme || 'light')
  // Which row's transcript is shown in the slide-over trajectory drawer.
  const [openTx, setOpenTx] = useState(null)
  // Whether the "Add your skill" how-to popup is open.
  const [guideOpen, setGuideOpen] = useState(false)
  // Whether the "preview & download" info popup is open (shared by the notes and the (i) badge).
  const [infoOpen, setInfoOpen] = useState(false)

  // Mirror filter into a ref so the WS handler reads the latest value without re-subscribing.
  const filterRef = useRef(false)
  useEffect(() => { filterRef.current = !!filter }, [filter])

  // Apply a dataset (initial fetch or live snapshot). Index transcripts so each row
  // finds its conversation; leave the visible rows alone while a filter is active.
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
    // Initial load over HTTP - works even if the WebSocket is blocked. One /snapshot
    // call returns feedback + their matching transcripts + stats, the same correlated
    // shape the live WS pushes, so every row finds its trajectory.
    fetch(`${API_BASE}/snapshot`).then(okJson)
      .then((d) => applyData(d.feedback ?? [], d.transcripts ?? [], d.stats ?? []))
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false))
  }, [applyData])

  // Connect to /ws, apply each pushed snapshot, and auto-reconnect on a drop.
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
            setLiveTick((n) => n + 1) // nudge an active filter to re-run against fresh data
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

  // While filtering, resolve trajectories from the filter's own index (its rows' transcripts);
  // otherwise from the live preview index.
  const transcriptFor = (r) => {
    const index = filter ? filterByKey : byKey
    return index[`r:${r.request_id}`] || index[`s:${r.session_id}`] || null
  }

  // A filter replaces the table's rows in place (with their own transcripts); Clear restores
  // the full list.
  const applyFilter = (resultRows, transcripts, meta) => {
    setRows(resultRows)
    setFilterByKey(indexTranscripts(transcripts))
    setFilter(meta)
  }
  const clearFilter = () => {
    setRows(allRows)
    setFilterByKey({})
    setFilter(null)
  }

  return (
    <div className="app" style={{ color: 'var(--text)' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', marginBottom: 18 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {/* Logo mask filled with the wordmark gradient so the two read as one unit. */}
          <span className="brand-logo" role="img" aria-label="RateXp logo" />
          <h1 style={{ margin: 0 }}>RateXp</h1>
          <span style={{ marginLeft: 4 }}><LiveDot live={live} /></span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          {/* Opens the how-to popup for skill authors. */}
          <button
            className="btn-edge"
            onClick={() => setGuideOpen(true)}
            title="How to send your skill's feedback to RateXp"
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 7,
              whiteSpace: 'nowrap',
              padding: '9px 16px',
              lineHeight: 1.2,
            }}
          >
            Add RateXp to your skill
          </button>
          {/* Sliding sun/moon switch; theme state drives [data-theme] on <html>, which the CSS keys off. */}
          <button
            className="theme-toggle"
            onClick={toggleTheme}
            role="switch"
            aria-checked={theme === 'light'}
            aria-label="Toggle light and dark theme"
            title="Toggle Sunburst / Midnight"
          >
            <svg className="ico sun" viewBox="0 0 24 24" aria-hidden="true">
              <circle cx="12" cy="12" r="5" fill="#ff8a1e" />
              <g stroke="#ff8a1e" strokeWidth="2.4" strokeLinecap="round">
                <line x1="12" y1="1.5" x2="12" y2="4" />
                <line x1="12" y1="20" x2="12" y2="22.5" />
                <line x1="1.5" y1="12" x2="4" y2="12" />
                <line x1="20" y1="12" x2="22.5" y2="12" />
                <line x1="4.2" y1="4.2" x2="6" y2="6" />
                <line x1="18" y1="18" x2="19.8" y2="19.8" />
                <line x1="4.2" y1="19.8" x2="6" y2="18" />
                <line x1="18" y1="6" x2="19.8" y2="4.2" />
              </g>
            </svg>
            <svg className="ico moon" viewBox="0 0 24 24" aria-hidden="true">
              <path d="M21 12.9A8.5 8.5 0 1 1 11.1 3 6.6 6.6 0 0 0 21 12.9Z" fill="#4aa3ff" />
            </svg>
            <span className="knob" aria-hidden="true" />
          </button>
        </div>
      </div>
      {(loading || error || filter) && (
        <p style={{ color: 'var(--muted)', marginTop: 4 }}>
          <StatusLine loading={loading} error={error} filtered={!!filter} />
        </p>
      )}
      <div className="glow-edge" style={groupBox}>
        <FilterBar apiBase={API_BASE} rows={rows} active={!!filter} liveTick={liveTick} onFilter={applyFilter} onClear={clearFilter} onInfo={() => setInfoOpen(true)} />
        {!loading && !error && filter?.truncated && <ViewLimitNotice shown={rows.length} />}
        {!loading && !error && (
          <section className="glow-edge" style={glassCard}>
            <h2 style={cardHeading}>Feedback</h2>
            <PreviewNote onInfo={() => setInfoOpen(true)} />
            {/* Scrolls sideways inside the card on tight widths instead of overflowing. */}
            <div className="table-scroll">
            <table className="data-table" style={{ borderCollapse: 'collapse', width: '100%', fontSize: 14, marginTop: 12 }}>
              <thead>
                <tr>
                  <Th>When</Th>
                  <Th>Skill</Th>
                  <Th>Agent</Th>
                  <Th>Score</Th>
                  <Th>Comment</Th>
                  <Th>Trajectory</Th>
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
                    <Td label="Trajectory"><Trajectory transcript={transcriptFor(r)} onOpen={(t) => setOpenTx({ transcript: t, row: r })} /></Td>
                    <Td label="Session"><code style={{ fontSize: 11 }}>{r.session_id}</code></Td>
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
          </section>
        )}
      </div>
      {!loading && !error && (
        <div className="glow-edge" style={groupBox}>
          <TopSkills skills={stats} />
        </div>
      )}
      {/* Subtle credit: barely above the background, brightens on hover. */}
      <footer className="app-footer">
        developed by{' '}
        <a href="https://www.linkedin.com/in/hikmetb/" target="_blank" rel="noopener noreferrer">
          Hikmet B.
        </a>
      </footer>
      <TrajectoryDrawer data={openTx} onClose={() => setOpenTx(null)} />
      <SkillGuideModal open={guideOpen} onClose={() => setGuideOpen(false)} />
      <DownloadInfoModal open={infoOpen} onClose={() => setInfoOpen(false)} />
    </div>
  )
}

// Short red note under the Feedback heading: the table is a real-time preview of the
// latest rows only (capped in app-be config). The full story - including how Download
// JSON behaves per query - lives in the shared info popup. Hidden while filtering.
function PreviewNote({ onInfo }) {
  return (
    <p style={{ margin: '10px 0 0', color: 'var(--danger)', fontWeight: 700, fontSize: 13 }}>
      This is a real-time preview - only the most recent entries are shown to keep
      things smooth. To see everything for your skill, query it with SQL above, then
      click Download JSON.{' '}
      <button type="button" className="link-inline" onClick={onInfo}>click <b>here</b> for more details</button>
    </p>
  )
}

function okJson(r) {
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return r.json()
}

// Index transcripts by request_id (1:1) then session_id (fallback) so a row finds its conversation.
function indexTranscripts(transcripts) {
  const index = {}
  for (const t of transcripts) {
    if (t.request_id) index[`r:${t.request_id}`] = t
    if (t.session_id) index[`s:${t.session_id}`] = t
  }
  return index
}

// Dot showing whether the live WebSocket is connected: green when streaming, grey when offline.
function LiveDot({ live }) {
  return (
    <span
      title={live ? 'Live - updating in real time' : 'Offline - not receiving live updates'}
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

// The most-rated skills and their good/bad score (GET /stats/top-skills).
function TopSkills({ skills }) {
  if (!skills || skills.length === 0) return null
  return (
    <section className="glow-edge" style={glassCard}>
      <h2 style={cardHeading}>Top skills</h2>
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

// Shown when a filter has more matches than the view size; points to Download JSON for all of them.
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
      Showing the first <strong>{shown}</strong> rows - you have more than the view limit.
      To see all, use <strong>Download JSON</strong> above.
    </p>
  )
}

const EXAMPLE_SQL = "SELECT * FROM feedback WHERE skill_name = '...'"

// SELECT-only SQL box that filters the table in place (Clear restores it). The
// backend enforces the guardrails (SELECT-only, read-only, timeout, row cap).
function FilterBar({ apiBase, rows, active, liveTick, onFilter, onClear, onInfo }) {
  const [sql, setSql] = useState('') // what's in the textarea
  const [appliedSql, setAppliedSql] = useState('') // the query currently filtering the table
  const [err, setErr] = useState(null)
  const [running, setRunning] = useState(false)

  // Run a query and push its rows + their transcripts into the table. `silent` skips the
  // spinner - used by the live refresh so the filtered view keeps up without flicker.
  const execute = useCallback((sqlToRun, { silent = false } = {}) => {
    if (!silent) setRunning(true)
    setErr(null)
    return fetch(`${apiBase}/query`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ sql: sqlToRun }),
    })
      .then(async (r) => {
        const body = await r.json().catch(() => ({}))
        if (!r.ok) throw new Error(body.detail || `HTTP ${r.status}`)
        return body
      })
      .then((body) => onFilter(body.rows, body.transcripts ?? [], { truncated: body.truncated }))
      .catch((e) => setErr(String(e.message || e)))
      .finally(() => { if (!silent) setRunning(false) })
  }, [apiBase, onFilter])

  const run = () => {
    setAppliedSql(sql)
    execute(sql)
  }

  const clear = () => {
    setSql('')
    setAppliedSql('')
    setErr(null)
    onClear()
  }

  // Live refresh: when new data streams in (liveTick) and a filter is applied, re-run it
  // silently so the filtered table updates in real time, just like the unfiltered view.
  useEffect(() => {
    if (appliedSql) execute(appliedSql, { silent: true })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [liveTick])

  // Export feedback as JSON, attaching each row's full ATIF trajectory under `conversation`.
  // With an active query we re-run it as a full export; the backend applies the download
  // rule over the whole result (single skill -> all of it; otherwise the 10 most recent).
  // With no query we just take the most recent preview rows already on screen.
  const download = async () => {
    setErr(null)
    try {
      let exportRows
      if (appliedSql.trim()) {
        const r = await fetch(`${apiBase}/query`, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ sql: appliedSql, full: true }),
        })
        const body = await r.json().catch(() => ({}))
        if (!r.ok) throw new Error(body.detail || `HTTP ${r.status}`)
        exportRows = body.rows
      } else {
        exportRows = rows.slice(0, 10)
      }
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
    <section className="glow-edge" style={glassCard}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <h2 style={cardHeading}>Filter with SQL</h2>
        {/* Opens the same preview & download info popup the red notes link to. */}
        <button
          type="button"
          className="info-badge"
          onClick={onInfo}
          title="Preview & download details"
          aria-label="Preview and download details"
        >
          i
        </button>
      </div>
      <p style={{ color: 'var(--muted)', fontSize: 13, marginTop: 8 }}>
        Read-only SELECT (capped & time-limited) that replaces the table below - query one
        skill, e.g. <code>SELECT * FROM feedback WHERE skill_name = '...'</code>, then Download
        JSON to export all of it.{' '}
        <button type="button" className="link-inline" onClick={onInfo}>click <b>here</b> for more details</button>
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
        <button className="btn-edge" onClick={run} disabled={running || !sql.trim()}>{running ? 'Filtering...' : 'Apply filter'}</button>
        <button className="btn-edge" onClick={clear} disabled={!active && !sql}>Clear</button>
        <button className="btn-edge" onClick={download} disabled={rows.length === 0}>Download JSON</button>
        {err && <span style={{ color: 'var(--danger)', fontSize: 13 }}>{err}</span>}
      </div>
    </section>
  )
}

// Each row links to its trajectory, opened in a slide-over drawer (see TrajectoryDrawer),
// plus a download button that saves just this row's ATIF as a JSON file.
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

// A tool call: a chip with the tool name, expandable to its JSON arguments if any.
function ToolCall({ call }) {
  const args =
    call.arguments && Object.keys(call.arguments).length > 0
      ? JSON.stringify(call.arguments, null, 2)
      : null
  if (!args) return <div className="tl-tool">⌗ {call.name}</div>
  return (
    <details className="tl-tool" open>
      <summary>⌗ {call.name}</summary>
      <pre className="tl-tool-args">{args}</pre>
    </details>
  )
}

// Slide-over panel showing one trajectory as a vertical timeline. Closes on the
// backdrop, the X, or Escape. `data` is the chosen transcript (+ its row) or null.
// Lock the background page scroll while an overlay (drawer/modal) is open, so on
// touch screens the scroll stays inside the overlay instead of leaking to the
// page behind it. Restores the page's prior scroll position on close.
function useBodyScrollLock(active) {
  useEffect(() => {
    if (!active) return
    const { body } = document
    const scrollY = window.scrollY
    const prev = { position: body.style.position, top: body.style.top, width: body.style.width, overflow: body.style.overflow }
    // position:fixed (not just overflow:hidden) is what iOS Safari actually honours.
    body.style.position = 'fixed'
    body.style.top = `-${scrollY}px`
    body.style.width = '100%'
    body.style.overflow = 'hidden'
    return () => {
      Object.assign(body.style, prev)
      window.scrollTo(0, scrollY)
    }
  }, [active])
}

function TrajectoryDrawer({ data, onClose }) {
  useBodyScrollLock(!!data)
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

  // Portal to <body> so the fixed drawer anchors to the viewport, not #root
  // (whose load animation's transform would otherwise offset it by the page
  // scroll on mobile, making the drawer open mid-scroll instead of at the top).
  return createPortal(
    <>
      <div className="drawer-backdrop" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-label="Trajectory">
        <header className="drawer-head">
          <div className="drawer-head-main">
            <div className="drawer-title">Trajectory</div>
            {/* Each fact gets a small KEY label (Skill, Agent, Model, Score, Steps, Tokens). */}
            <div className="drawer-meta">
              {[
                row?.skill_name && { k: 'Skill', v: <code>{row.skill_name}</code> },
                row?.agent && { k: 'Agent', v: <code>{row.agent}</code> },
                model && { k: 'Model', v: model },
                row?.score && { k: 'Score', v: scoreLabel(row.score) },
                { k: 'Steps', v: fm.total_steps ?? steps.length },
                {
                  k: 'Tokens',
                  v: `↑ ${fm.total_prompt_tokens ?? 0} · ↓ ${fm.total_completion_tokens ?? 0}`,
                  title: 'Totals across all agent turns — ↑ input (cached context included) · ↓ output. Summed per turn, so this is tokens processed, not conversation size.',
                },
              ]
                .filter(Boolean)
                .map((m, i) => (
                  <span className="dm-item" key={i} title={m.title}>
                    <span className="dm-key">{m.k}</span>
                    <span className="dm-val">{m.v}</span>
                  </span>
                ))}
            </div>
            {/* Always-visible note so the Tokens figure isn't misread: the arrows are
                input/output, and the totals are summed over every turn (history is
                re-sent each turn), so they measure tokens processed, not chat size.
                The rest explains why the steps below read shorter than that total. */}
            <p className="drawer-meta-note">
              ↑ input · ↓ output, summed across all turns — tokens processed, bigger than the trajectory looks. The tokens number above counts the conversation re-read and duplicated every turn; the trajectory below shows that same conversation de-duplicated.
            </p>
          </div>
          <button className="drawer-close" onClick={onClose} aria-label="Close">✕</button>
        </header>

        <div className="drawer-body">
          {atif.oversized && (
            <p className="tl-oversized">{atif.oversized.message}</p>
          )}
          <ol className="timeline">
            {steps.map((s, i) => (
              <li key={i} className="tl-step" style={{ animationDelay: `${Math.min(i * 40, 400)}ms` }}>
                <span className={`tl-dot tl-${s.source}`} />
                <div className={`tl-card tl-card-${s.source}`}>
                  <div className="tl-role" style={sourceStyle(s.source)}>{s.source}</div>
                  {s.reasoning_content && (
                    <details className="tl-reason" open>
                      <summary>reasoning</summary>
                      <Md className="md md-muted">{s.reasoning_content}</Md>
                    </details>
                  )}
                  {s.message && <Md className="md">{s.message}</Md>}
                  {Array.isArray(s.tool_calls) &&
                    s.tool_calls.map((t, j) => <ToolCall key={j} call={t} />)}
                  {s.observation && (
                    <details className="tl-obs" open>
                      <summary>↳ output</summary>
                      <Md className="md md-muted">{s.observation}</Md>
                    </details>
                  )}
                </div>
              </li>
            ))}
          </ol>
        </div>
      </aside>
    </>,
    document.body,
  )
}

// Centered how-to popup for skill authors (SKILL_GUIDE_MD). Closes on the backdrop, the X, or Escape.
function SkillGuideModal({ open, onClose }) {
  useBodyScrollLock(open)
  useEffect(() => {
    if (!open) return
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null
  // Portal to <body> so the fixed backdrop anchors to the viewport, not #root
  // (whose load animation would otherwise offset the centered popup on mobile).
  return createPortal(
    <>
      <div className="drawer-backdrop" onClick={onClose} />
      <div className="modal-wrap" onClick={onClose}>
        <div className="modal glow-edge" role="dialog" aria-label="Add RateXp to your skill" onClick={(e) => e.stopPropagation()}>
          <button className="modal-close" onClick={onClose} aria-label="Close">✕</button>
          <Md className="md modal-md">{SKILL_GUIDE_MD}</Md>
        </div>
      </div>
    </>,
    document.body,
  )
}

// Centered popup explaining the real-time preview and how Download JSON behaves
// (DOWNLOAD_INFO_MD). Same look as SkillGuideModal; closes on the backdrop, the X, or Escape.
function DownloadInfoModal({ open, onClose }) {
  useBodyScrollLock(open)
  useEffect(() => {
    if (!open) return
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null
  return createPortal(
    <>
      <div className="drawer-backdrop" onClick={onClose} />
      <div className="modal-wrap" onClick={onClose}>
        <div className="modal glow-edge" role="dialog" aria-label="Preview and download details" onClick={(e) => e.stopPropagation()}>
          <button className="modal-close" onClick={onClose} aria-label="Close">✕</button>
          <Md className="md modal-md">{DOWNLOAD_INFO_MD}</Md>
        </div>
      </div>
    </>,
    document.body,
  )
}

// Render an ATIF step's text as Markdown (GFM). Styling lives under .md in index.css.
// (react-markdown v9 has no className prop, so we wrap it in a div.)
function Md({ className, children }) {
  return (
    <div className={className}>
      <Markdown remarkPlugins={[remarkGfm]}>{String(children ?? '')}</Markdown>
    </div>
  )
}

// Cell styling lives in index.css (.th/.td) so the mobile breakpoint can restyle
// the table into cards. `label` becomes data-label, the card row's heading on phones.
function Th({ children }) { return <th className="th">{children}</th> }
function Td({ children, label }) { return <td className="td" data-label={label}>{children}</td> }
function Dash() { return <span style={{ color: 'var(--faint)' }}>—</span> }

function sourceStyle(source) {
  const color = source === 'user' ? 'var(--accent-2)' : source === 'agent' ? 'var(--good)' : 'var(--faint)'
  return { fontSize: 11, textTransform: 'uppercase', letterSpacing: '.04em', color, fontWeight: 600 }
}

// Colored label so good/bad reads at a glance - plain text, no bounding box.
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
  if (loading) return 'Loading...'
  if (error) return <span style={{ color: 'var(--danger)' }}>{error}</span>
  if (filtered) return 'Filtered'
  return null
}
