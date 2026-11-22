import type { EngineInterface, Register } from 'claude-code'

// The RateXp rating panel: what to evaluate, a True or False for each eval, consent, and
// one comment for every rating sent, in four tabs, with Send and Skip. It opens on
// /ratexp:rate and, every Nth turn, when ratexp-claude.sh (beside the plugin's manifest)
// marks the survey due. That script owns the evals, the session's state and every
// request to core: the panel only asks.

const PANE = 'ratexp-rate'
const TABS = ['Eval what', 'Evals', 'Store', 'Comment']

type Eval = {
  name: string
  question: string
  good: string
  good_description: string
  bad: string
  bad_description: string
}
type Survey = { due: boolean; consent: string; skill: string | null; evals: Eval[] }
type Verdict = 'good' | 'bad'

// What the open panel shows and what the user has chosen so far.
let survey: Survey | null = null
let tab = 0
let isSessionRated = true
let isSkillRated = false
let verdicts: Record<string, Verdict | undefined> = {}
let isStored = true
let comment = ''
let isSending = false
// Where the keyboard is in the panel, as the ui.focus hook last saw it.
let focused: string | undefined
// The sessions whose Stop hook already knows the panel asks.
const panelSessions = new Set<string>()

function runScript($: EngineInterface, args: string[], stdin?: string) {
  return $.process.run(['bash', `${$.plugin.root}/ratexp-claude.sh`, ...args], {
    stdin,
    // Sending waits on core, and a core that just started takes about 30 s.
    timeoutMs: 120_000,
  })
}

function redraw($: EngineInterface) {
  $.ui.invalidate('ui.render')
}

function ratedTargets(): string[] {
  const targets: string[] = []
  if (isSessionRated) targets.push('')
  if (isSkillRated && survey?.skill) targets.push(survey.skill)
  return targets
}

function ratedEvals(): Eval[] {
  return survey?.evals.filter(one => verdicts[one.name]) ?? []
}

// Opens the panel with the survey the script describes. Unasked (every Nth turn) it
// opens only when the script says the survey is due. Returns a line for the user when
// the panel cannot open.
async function openPanel($: EngineInterface, session: string, isAsked: boolean): Promise<string | undefined> {
  const { stdout } = await runScript($, ['panel', session])
  let found: Survey & { error?: string }
  try {
    found = JSON.parse(stdout)
  } catch {
    return 'RateXp: the rating panel could not be loaded.'
  }
  if (found.error) return found.error
  if (!isAsked && !found.due) return undefined
  survey = found
  tab = 0
  isSessionRated = true
  isSkillRated = false
  verdicts = {}
  isStored = true
  comment = ''
  isSending = false
  focused = undefined
  // Opening a panel that is already open only retitles it, and leaves the keyboard where
  // it is: a fresh one takes the keyboard.
  if ((await $.ui.panes()).some(pane => pane.id === PANE)) await $.ui.close({ id: PANE })
  const opened = await $.ui.open({ id: PANE, title: 'RateXp', focus: true, closeOnEscape: true, rows: 18 })
  // Claude Code keeps the pane's last drawing and would show it again, with the last
  // survey's tab, ticks and comment: a new survey is drawn afresh.
  redraw($)
  return opened.isPlaced || !isAsked ? undefined : `RateXp: the rating panel could not open (${opened.reason}).`
}

// The open tab's controls, in the order the up and down arrows walk them.
function tabControls(): string[] {
  if (!survey) return []
  if (tab === 0) return survey.skill ? ['rate-session', 'rate-skill'] : ['rate-session']
  if (tab === 1) return survey.evals.flatMap(one => [`good-${one.name}`, `bad-${one.name}`])
  if (tab === 2) return ['store-yes', 'store-no']
  return ['comment']
}

// Opens tab <i> with the keyboard on its first control. Claude Code would otherwise leave
// the keyboard where the old tab had it, which can be a tab button, and letters typed on a
// button go to the prompt, not the comment field.
async function showTab($: EngineInterface, i: number) {
  tab = i
  redraw($)
  await focusOn($, tabControls()[0] ?? 'send')
}

// Puts the keyboard on one of the panel's controls. A panel that does not hold the keys
// refuses, and the person then moves on with the arrows. Where the keyboard is there
// already (Claude Code moved it there itself on a tab switch), nothing moves and no
// ui.focus fires, so the landing is noted here too.
async function focusOn($: EngineInterface, key: string) {
  const result = await $.ui.focus({ requestId: PANE, key }).catch(() => ({ deny: 'refused' }))
  if (!('deny' in result)) focused = key
}

// The stops a survey with nothing to evaluate locks: the other tabs and Send.
const LOCKED = TABS.slice(1).map((_, i) => `tab-${i + 1}`).concat('send')

// Where a move of the person's arrows or Tab lands, from the control <from> to the stop
// Claude Code picked (<to>). Within the open tab's <controls> it stays as picked. Past the
// last control, where Claude Code goes on to the first tab's button (the down arrow) or
// the pane's close mark (Tab, <to> absent), it goes to <after>; before the first control,
// where Claude Code goes back to Skip, it goes to <before>. A <locked> stop is passed
// over: to Skip, or back from Skip to the first tab.
export function focusLanding(
  controls: readonly string[],
  from: string | undefined,
  to: string | undefined,
  after: string,
  before: string,
  locked: readonly string[] = [],
) {
  if (to !== undefined && controls.includes(to)) return to
  if (from === controls[controls.length - 1] && (to === undefined || to === 'tab-0')) return after
  if (from === controls[0] && to === 'skip') return before
  if (to !== undefined && locked.includes(to)) return from === 'skip' ? 'tab-0' : 'skip'
  return to
}

// Hands every rated eval of every rated target, each with the one comment, to the script,
// closes the panel and leaves the script's result line in the conversation.
async function sendRatings($: EngineInterface) {
  if (!survey || isSending) return
  const targets = ratedTargets()
  const evals = ratedEvals()
  if (targets.length === 0 || evals.length === 0) return
  isSending = true
  redraw($)
  const session = await $.session.id()
  const { transcriptPath } = await $.session.info()
  const fields = [transcriptPath, isStored ? 'yes' : 'no']
  for (const target of targets) {
    for (const one of evals) {
      fields.push(target, one.name, verdicts[one.name] ?? '', comment.replace(/\0/g, ''))
    }
  }
  let line: string
  try {
    const sent = await runScript($, ['send', session], fields.map(field => `${field}\0`).join(''))
    line = sent.stdout.trim() || 'RateXp: feedback could not be sent.'
  } catch {
    line = 'RateXp: feedback could not be sent.'
  }
  survey = null
  await $.ui.close({ id: PANE })
  $.ui.log(shownLine(line))
}

// A line of the script's, or the panel's own, as the conversation shows it: Claude Code
// already puts the plugin's name before it.
function shownLine(line: string) {
  return line.replace(/^RateXp: /, '')
}

// Closes the panel and sends nothing: the rating is skipped.
async function skipRating($: EngineInterface) {
  survey = null
  await $.ui.close({ id: PANE })
}

function box(isTicked: boolean) {
  return isTicked ? '[x]' : '[ ]'
}

// An eval's answer, its box after the label ("True [x]"), the label padded to <width>
// so the boxes of one question stand in a column.
function answerTick(label: string, isTicked: boolean, width: number) {
  return `${label.padEnd(width)} ${box(isTicked)}`
}

// A session with nothing to draw on (a `claude -p` run) keeps the picker the script
// hands the model instead.
async function canDraw($: EngineInterface) {
  return (await $.session.surfaces()).length > 0
}

export const register: Register = on => {
  on('command.run', { command: 'ratexp:rate' }, async ($, e, next) => {
    if (!(await canDraw($))) return next(e)
    const problem = await openPanel($, await $.session.id(), true)
    return { text: shownLine(problem ?? 'the rating panel is open.') }
  }).catch(($, e, next) => (next.called ? next(e) : { text: 'the rating panel could not open.' }))

  // The script's Stop hook counts the turns and marks the survey due; the panel opens
  // it once that hook has run. A failure here must never cost the turn that hook.
  on('classic.Stop', async ($, e, next) => {
    const session = e.session_id
    if (!(await canDraw($))) return next(e)
    if (session && !panelSessions.has(session)) {
      await runScript($, ['panel-on', session])
      panelSessions.add(session)
    }
    const result = await next(e)
    // Another Stop hook that blocks keeps the turn going: the survey waits for its end.
    const isTurnGoingOn = result.block !== undefined
    const isPanelOpen = (await $.ui.panes()).some(pane => pane.id === PANE)
    if (session && !isTurnGoingOn && !isPanelOpen) await openPanel($, session, false)
    return result
  }).catch(($, e, next) => next(e))

  // The person's moves land as focusLanding says: out of a tab, on to the next tab's
  // button (Send after the last tab), or to Skip when nothing is ticked to evaluate. A
  // failure here leaves the keyboard to Claude Code's own move.
  on('ui.focus', { component: 'Pane', requestId: PANE }, async ($, e, next) => {
    const isLocked = ratedTargets().length === 0
    const after = isLocked ? 'skip' : tab < TABS.length - 1 ? `tab-${tab + 1}` : 'send'
    const target =
      e.origin.kind === 'person'
        ? focusLanding(tabControls(), focused, e.element, after, `tab-${tab}`, isLocked ? LOCKED : [])
        : e.element
    const result = await next(target === e.element ? e : { ...e, element: target })
    if (!('deny' in result)) focused = target
    return result
  }).catch(($, e, next) => next(e))

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Button, Input, Text } = $.ui.resolve(e)
    if (!survey) return <Text dimColor>RateXp</Text>
    const shown = survey
    const count = ratedTargets().length * ratedEvals().length
    // With nothing ticked to evaluate, the other tabs and Send are struck through and do
    // nothing.
    const isLocked = ratedTargets().length === 0

    const tabs = (
      <Box gap={2}>
        <Text bold color="yellow">
          RateXp
        </Text>
        {TABS.map((title, i) => (
          <Button key={`tab-${i}`} hotkey={`${i + 1}`} onPress={() => (isLocked && i > 0 ? undefined : showTab($, i))}>
            <Text
              bold={i === tab}
              color={i === tab ? 'yellow' : undefined}
              dimColor={i !== tab}
              strikethrough={isLocked && i > 0}
            >
              {title}
            </Text>
          </Button>
        ))}
        <Button key="send" variant="primary" dimColor={count === 0 || isSending} onPress={() => sendRatings($)}>
          <Text strikethrough={isLocked}>{isSending ? 'Sending…' : 'Send'}</Text>
        </Button>
        <Button key="skip" label="Skip" onPress={() => skipRating($)} />
      </Box>
    )

    let body
    if (tab === 0) {
      body = (
        <Box flexDirection="column">
          <Button key="rate-session" plain autoFocus onPress={() => ((isSessionRated = !isSessionRated), redraw($))}>
            {`${box(isSessionRated)} This session`}
          </Button>
          {shown.skill ? (
            <Button key="rate-skill" plain onPress={() => ((isSkillRated = !isSkillRated), redraw($))}>
              {`${box(isSkillRated)} Last skill: ${shown.skill}`}
            </Button>
          ) : (
            <Text dimColor>    (no skill has run yet)</Text>
          )}
        </Box>
      )
    } else if (tab === 1) {
      const pick = (name: string, verdict: Verdict) => () => {
        verdicts = { ...verdicts, [name]: verdicts[name] === verdict ? undefined : verdict }
        redraw($)
      }
      body = (
        <Box flexDirection="column">
          {shown.evals.map(one => {
            const width = Math.max(one.good.length, one.bad.length)
            return (
              <Box key={`eval-${one.name}`} flexDirection="column">
                <Text bold>{one.question}</Text>
                <Box gap={1}>
                  <Button key={`good-${one.name}`} plain onPress={pick(one.name, 'good')}>
                    <Text color="green">{answerTick(one.good, verdicts[one.name] === 'good', width)}</Text>
                  </Button>
                  <Text dimColor>{one.good_description}</Text>
                </Box>
                <Box gap={1}>
                  <Button key={`bad-${one.name}`} plain onPress={pick(one.name, 'bad')}>
                    <Text color="red">{answerTick(one.bad, verdicts[one.name] === 'bad', width)}</Text>
                  </Button>
                  <Text dimColor>{one.bad_description}</Text>
                </Box>
              </Box>
            )
          })}
        </Box>
      )
    } else if (tab === 2) {
      body = (
        <Box flexDirection="column">
          <Box gap={2}>
            <Text>Store trajectory?</Text>
            <Button key="store-yes" plain onPress={() => ((isStored = true), redraw($))}>
              {`${box(isStored)} yes`}
            </Button>
            <Button key="store-no" plain onPress={() => ((isStored = false), redraw($))}>
              {`${box(!isStored)} no`}
            </Button>
          </Box>
          <Text dimColor>{`yes: ${shown.consent}`}</Text>
        </Box>
      )
    } else {
      body = (
        <Box flexDirection="column">
          <Input
            key="comment"
            label="Comment"
            placeholder="sent with every rating"
            value={comment}
            onInput={(text: string) => {
              comment = text
            }}
            onSubmit={(text: string) => {
              comment = text
              redraw($)
              // Enter in the comment is done with it: the keyboard goes to Send.
              void focusOn($, 'send')
            }}
          />
        </Box>
      )
    }

    return (
      <Box flexDirection="column" gap={1}>
        {tabs}
        {body}
        <Text dimColor>↑↓ move · Enter ticks or presses · 1-4 tabs · click works · Esc skips</Text>
      </Box>
    )
  })
}
