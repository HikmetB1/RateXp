// Tests for plugins/claude-code/hooks/rating-panel.tsx, the Claude Code rating panel.
// test_rating_panel.py copies this file into the plugin's hooks/ folder in a scratch copy
// and runs `claude plugin test` there, so the panel's module sits beside it. Each hook
// below stands for the engine; the script the panel runs (ratexp-claude.sh) is answered
// here too, so nothing leaves the test. The kit answers no focus moves, so where the
// arrows land is tested on focusLanding itself. The clock is the kit's mock: the line that
// plays where a survey closed moves only as a test advances it.
import { expect, mock, test } from 'claude-code/testing'
import { focusLanding, isFeedbackStored, panelSite } from './rating-panel.tsx'

const PANE = {
  plugin: 'ratexp',
  component: 'Pane',
  requestId: 'ratexp-rate',
  props: {
    title: 'RateXp',
    isFocused: true,
    bodyColumns: 100,
    placement: 'dock',
    scroll: { offset: 0, bodyRows: 20 },
    view: {},
  },
} as const

// The band above the prompt, where an unasked survey shows.
const BAND = {
  plugin: 'ratexp',
  component: 'AbovePrompt',
  props: {
    hasSurvey: false,
    isCollapsed: false,
    isWorking: false,
    maxRows: 20,
    bodyColumns: 100,
    scroll: { offset: 0, bodyRows: 19 },
    view: {},
  },
} as const

const SURVEY = {
  due: false,
  skill: 'poem-creator',
  evals: [
    {
      name: 'human-satisfaction',
      question: 'Are you satisfied?',
      good: 'True',
      good_description: 'It met my expectations.',
      bad: 'False',
      bad_description: 'It fell short.',
    },
    {
      name: 'human-time-saved',
      question: 'Did it make you faster?',
      good: 'True',
      good_description: 'It saved me time.',
      bad: 'False',
      bad_description: 'It took as long or longer.',
    },
  ],
}

type Run = { argv: readonly string[]; stdin?: string }

const STORED = 'RateXp: feedback and transcripts accepted by https://core.test for 2 ratings.\n'
const SORRY = "Sorry, we didn't hear from you. /ratexp:rate opens it again."
// The sorry as the band shows it once typed: whole, and nothing else.
const SORRY_SHOWN = new RegExp(`^${SORRY.replace(/[./]/g, '\\$&')}$`)
const GLAD = "We're very glad we heard from you!"
const PURPLE = '#a855f7'
const ORANGE = '#ff8a1e'

// The engine's answers a panel session needs, and every script run, log line and toast
// kept. <survey> is read at each run of the script, so a test can change it between turns.
function engine(on: any, { surfaces = ['terminal'], survey = SURVEY, sendLine = STORED } = {}) {
  const runs: Run[] = []
  const logs: string[] = []
  const toasts: string[] = []
  const opened: string[] = []
  const closed: string[] = []
  const clock = mock.clock(on)
  on('session.surfaces', () => ({ value: surfaces }))
  on('session.id', () => ({ value: 'session-1' }))
  on('session.info', () => ({ value: { transcriptPath: '/tmp/session-1.jsonl' } }))
  on('ui.panes', () => ({ value: [] }))
  on('ui.open', (_: unknown, e: { id: string }) => (opened.push(e.id), { value: { isPlaced: true } }))
  on('ui.close', (_: unknown, e: { id: string }) => (closed.push(e.id), { value: undefined }))
  on('ui.log', (_: unknown, e: { text: string }) => (logs.push(e.text), { value: undefined }))
  on('ui.toast', (_: unknown, e: { text: string }) => (toasts.push(e.text), { value: undefined }))
  on('process.run', (_: unknown, e: { argv: readonly string[]; init?: { stdin?: string } }) => {
    runs.push({ argv: e.argv, stdin: e.init?.stdin })
    const command = e.argv[2]
    const stdout =
      command === 'panel' ? JSON.stringify(survey) : command === 'send' ? sendLine : ''
    return { value: { exitCode: 0, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
  })
  return { runs, logs, toasts, opened, closed, clock }
}

// A turn's end, as Claude Code raises it once the script's Stop hook ran.
async function endTurn($: any) {
  await $.classic.Stop({ session_id: 'session-1', stop_hook_active: false })
}

function sent(runs: Run[]) {
  const send = runs.find(run => run.argv[2] === 'send')
  return send?.stdin?.split('\0').slice(0, -1)
}

test('/ratexp:rate opens the panel and sends each rated eval of each rated target', async ($, on) => {
  const { runs, logs, opened } = engine(on)
  const answer = await $.command.run({ command: 'ratexp:rate', args: 'any words' })
  expect(answer.text).toBe('the rating panel is open.')
  expect(opened).toEqual(['ratexp-rate'])

  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  await ui.press({ key: 'rate-skill' })
  await ui.press({ key: 'tab-1' })
  await ui.press({ key: 'good-human-satisfaction' })
  await ui.press({ key: 'tab-3' })
  await ui.input({ key: 'comment', text: 'nice', kind: 'change' })
  await ui.press({ key: 'send' })

  expect(runs.find(run => run.argv[2] === 'send')?.argv.slice(1)).toEqual(
    expect.arrayContaining(['send', 'session-1']),
  )
  expect(sent(runs)).toEqual([
    '/tmp/session-1.jsonl',
    'yes',
    '',
    'human-satisfaction',
    'good',
    'nice',
    'poem-creator',
    'human-satisfaction',
    'good',
    'nice',
  ])
  expect(logs).toEqual(['feedback and transcripts accepted by https://core.test for 2 ratings.'])
  await ui.unmount()
})

test('an eval left unticked is skipped, and one comment goes with every rating', async ($, on) => {
  const { runs } = engine(on)
  await $.command.run({ command: 'ratexp:rate', args: '' })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  await ui.press({ key: 'tab-1' })
  await ui.press({ key: 'bad-human-time-saved' })
  await ui.press({ key: 'good-human-satisfaction' })
  await ui.press({ key: 'tab-3' })
  await ui.input({ key: 'comment', text: 'too slow' })
  await ui.press({ key: 'send' })
  expect(sent(runs)).toEqual([
    '/tmp/session-1.jsonl',
    'yes',
    '',
    'human-satisfaction',
    'good',
    'too slow',
    '',
    'human-time-saved',
    'bad',
    'too slow',
  ])
  await ui.unmount()
})

test('without consent the script hears no', async ($, on) => {
  const { runs } = engine(on)
  await $.command.run({ command: 'ratexp:rate', args: '' })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  await ui.press({ key: 'tab-1' })
  await ui.press({ key: 'bad-human-time-saved' })
  await ui.press({ key: 'tab-2' })
  await ui.press({ key: 'store-no' })
  await ui.press({ key: 'send' })
  expect(sent(runs)).toEqual(['/tmp/session-1.jsonl', 'no', '', 'human-time-saved', 'bad', ''])
  await ui.unmount()
})

test('each answer shows what it means beside its button', async ($, on) => {
  engine(on)
  await $.command.run({ command: 'ratexp:rate', args: '' })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  await ui.press({ key: 'tab-1' })
  expect(await ui.find({ type: 'Text', text: /It saved me time\./ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /It took as long or longer\./ })).toBeDefined()
  await ui.unmount()
})

test('a survey opened again starts clean, on Eval what', async ($, on) => {
  engine(on)
  await $.command.run({ command: 'ratexp:rate', args: '' })
  let ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  await ui.press({ key: 'tab-1' })
  await ui.press({ key: 'good-human-satisfaction' })
  await ui.press({ key: 'tab-3' })
  await ui.input({ key: 'comment', text: 'old comment', kind: 'change' })
  await ui.press({ key: 'skip' })
  await ui.unmount()

  await $.command.run({ command: 'ratexp:rate', args: '' })
  ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect(await ui.find({ key: 'rate-session' })).toBeDefined()
  await ui.press({ key: 'tab-1' })
  expect((await ui.find({ key: 'good-human-satisfaction' }))?.text).toContain('[ ]')
  await ui.press({ key: 'tab-3' })
  expect((await ui.find({ key: 'comment' }))?.props.value).toBe('')
  await ui.unmount()
})

test('Send does nothing until something is rated', async ($, on) => {
  const { runs } = engine(on)
  await $.command.run({ command: 'ratexp:rate', args: '' })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect((await ui.find({ key: 'send' }))?.text).toBe('Send')
  await ui.press({ key: 'send' })
  expect(sent(runs)).toBeUndefined()
  await ui.unmount()
})

test('Skip closes the panel and sends nothing', async ($, on) => {
  const { runs, closed } = engine(on)
  await $.command.run({ command: 'ratexp:rate', args: '' })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  await ui.press({ key: 'tab-1' })
  await ui.press({ key: 'good-human-satisfaction' })
  await ui.press({ key: 'skip' })
  expect(closed.at(-1)).toBe('ratexp-rate')
  expect(sent(runs)).toBeUndefined()
  await ui.unmount()
})

test('without a skill that ran, only the session is offered', async ($, on) => {
  engine(on, { survey: { ...SURVEY, skill: null } })
  await $.command.run({ command: 'ratexp:rate', args: '' })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect(await ui.find({ key: 'rate-skill' })).toBeUndefined()
  expect(await ui.find({ type: 'Text', text: /no skill has run yet/ })).toBeDefined()
  await ui.unmount()
})

test('a session with nothing to draw on keeps the skill and its picker', async ($, on) => {
  const { runs, opened } = engine(on, { surfaces: [] })
  on('command.run', () => ({ text: 'the skill ran' }))
  const answer = await $.command.run({ command: 'ratexp:rate', args: '' })
  expect(answer.text).toBe('the skill ran')
  expect(runs).toEqual([])
  expect(opened).toEqual([])
})

test('a turn the script marked due opens the panel in the band after its Stop hook ran', async ($, on) => {
  const survey = { ...SURVEY, due: true }
  const { runs, opened } = engine(on, { survey })
  on('classic.Stop', () => ({}))
  await endTurn($)
  survey.due = false
  await endTurn($)
  // The script hears once that the panel asks in this session; each turn's end asks
  // whether a survey is due, and a turn that is not leaves the open one in the band.
  expect(runs.map(run => run.argv[2])).toEqual(['panel-on', 'panel', 'panel'])
  expect(opened).toEqual([])
  const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })
  expect((await ui.find({ key: 'send' }))?.text).toBe('Send')
  await ui.unmount()
})

test('the band shows how to use it, sends, thanks, and then draws nothing of RateXp', async ($, on) => {
  const { runs, logs, clock } = engine(on, { survey: { ...SURVEY, due: true } })
  on('classic.Stop', () => ({}))
  await endTurn($)
  const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: /^click to use/ })).toBeDefined()
  await ui.press({ key: 'tab-1' })
  await ui.press({ key: 'good-human-satisfaction' })
  await ui.press({ key: 'send' })
  expect(sent(runs)).toEqual(['/tmp/session-1.jsonl', 'yes', '', 'human-satisfaction', 'good', ''])
  expect(logs).toEqual(['feedback and transcripts accepted by https://core.test for 2 ratings.'])
  await clock.advance(1200)
  await ui.redraw()
  expect(await ui.find({ key: 'send' })).toBeUndefined()
  expect(await ui.find({ type: 'Text', text: new RegExp(GLAD) })).toBeDefined()
  await clock.advance(3000)
  await ui.redraw()
  expect(await ui.keepsBeneath()).toBe(true)
  await ui.unmount()
})

test('the thank-you types in, then shows whole in orange', async ($, on) => {
  const { clock } = engine(on, { survey: { ...SURVEY, due: true } })
  on('classic.Stop', () => ({}))
  await endTurn($)
  const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })
  await ui.press({ key: 'tab-1' })
  await ui.press({ key: 'good-human-satisfaction' })
  await ui.press({ key: 'send' })
  await clock.advance(500)
  await ui.redraw()
  // Halfway through the typing, half the words show, behind the cursor.
  expect(await ui.find({ type: 'Text', text: /^We're very g.*▌$/ })).toBeDefined()
  await clock.advance(700)
  await ui.redraw()
  expect(await ui.find({ type: 'Text', text: /▌/ })).toBeUndefined()
  // The line and its one coloured part read the same: the part is the innermost.
  expect((await ui.findAll({ type: 'Text', text: new RegExp(`^${GLAD}$`) })).at(-1)?.props.color).toBe(ORANGE)
  await ui.unmount()
})

test('a send core did not store gets its failure line and no thank-you', async ($, on) => {
  const { logs } = engine(on, {
    survey: { ...SURVEY, due: true },
    sendLine: 'RateXp: feedback could not be sent to https://core.test.\n',
  })
  on('classic.Stop', () => ({}))
  await endTurn($)
  const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })
  await ui.press({ key: 'tab-1' })
  await ui.press({ key: 'good-human-satisfaction' })
  await ui.press({ key: 'send' })
  expect(logs).toEqual(['feedback could not be sent to https://core.test.'])
  await ui.redraw()
  expect(await ui.keepsBeneath()).toBe(true)
  await ui.unmount()
})

test('only a line that says core accepted the feedback counts as stored', () => {
  expect(isFeedbackStored('RateXp: feedback accepted by https://core.test. Transcript kept private.')).toBe(true)
  expect(isFeedbackStored(STORED)).toBe(true)
  expect(isFeedbackStored('RateXp: feedback accepted by https://core.test. Transcript could not be sent.')).toBe(true)
  expect(isFeedbackStored('RateXp: feedback could not be sent to https://core.test.')).toBe(false)
  expect(isFeedbackStored('RateXp: feedback not sent: the ratings could not be read.')).toBe(false)
  expect(isFeedbackStored('RateXp: feedback could not be sent.')).toBe(false)
})

test('a new prompt closes the survey unsent, and the band says sorry in purple', async ($, on) => {
  const { runs, clock } = engine(on, { survey: { ...SURVEY, due: true } })
  on('classic.Stop', () => ({}))
  on('prompt.submit', (_: unknown, e: { text: string }) => ({ text: e.text }))
  await endTurn($)
  const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })
  await ui.press({ key: 'tab-1' })
  await ui.press({ key: 'good-human-satisfaction' })
  await $.prompt.submit({ text: 'next task' })
  await clock.advance(1200)
  await ui.redraw()
  expect(await ui.find({ key: 'send' })).toBeUndefined()
  expect(sent(runs)).toBeUndefined()
  expect(await ui.find({ type: 'Text', text: SORRY_SHOWN })).toBeDefined()
  expect((await ui.find({ type: 'Text', text: /^Sorry, we didn't hear from you\. $/ }))?.props.color).toBe(PURPLE)
  // The command stays dim, and the words after it are purple again.
  expect((await ui.find({ type: 'Text', text: /^\/ratexp:rate$/ }))?.props.dimColor).toBe(true)
  expect((await ui.find({ type: 'Text', text: /^ opens it again\.$/ }))?.props.color).toBe(PURPLE)
  await clock.advance(3000)
  await ui.redraw()
  expect(await ui.keepsBeneath()).toBe(true)
  await ui.unmount()
})

test('Skip says the same sorry', async ($, on) => {
  const { clock } = engine(on, { survey: { ...SURVEY, due: true } })
  on('classic.Stop', () => ({}))
  await endTurn($)
  const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })
  await ui.press({ key: 'skip' })
  await clock.advance(1200)
  await ui.redraw()
  expect(await ui.find({ type: 'Text', text: SORRY_SHOWN })).toBeDefined()
  await ui.unmount()
})

test('a new prompt closes a survey /ratexp:rate opened in a pane too', async ($, on) => {
  const { closed } = engine(on)
  on('prompt.submit', (_: unknown, e: { text: string }) => ({ text: e.text }))
  await $.command.run({ command: 'ratexp:rate', args: '' })
  await $.prompt.submit({ text: 'next task' })
  expect(closed.at(-1)).toBe('ratexp-rate')
})

test('/ratexp:rate typed as the next prompt leaves the survey to the command', async ($, on) => {
  engine(on, { survey: { ...SURVEY, due: true } })
  on('classic.Stop', () => ({}))
  on('prompt.submit', (_: unknown, e: { text: string }) => ({ text: e.text }))
  await endTurn($)
  await $.prompt.submit({ text: '/ratexp:rate', command: { name: 'ratexp:rate', args: '' } } as any)
  const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })
  expect(await ui.find({ key: 'send' })).toBeDefined()
  await ui.unmount()
})

test('a prompt that did not enter leaves the survey open', async ($, on) => {
  engine(on, { survey: { ...SURVEY, due: true } })
  on('classic.Stop', () => ({}))
  on('prompt.submit', () => ({ drop: 'blocked by a hook' }))
  await endTurn($)
  await $.prompt.submit({ text: 'next task' })
  const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })
  expect(await ui.find({ key: 'send' })).toBeDefined()
  await ui.unmount()
})

test('where no band shows, the sorry comes as a toast', async ($, on) => {
  const { toasts, closed } = engine(on, { surfaces: ['vscode'] })
  on('prompt.submit', (_: unknown, e: { text: string }) => ({ text: e.text }))
  await $.command.run({ command: 'ratexp:rate', args: '' })
  await $.prompt.submit({ text: 'next task' })
  expect(closed.at(-1)).toBe('ratexp-rate')
  expect(toasts).toEqual([SORRY])
})

test('a folded band gets the sorry as a toast', async ($, on) => {
  const { toasts } = engine(on, { survey: { ...SURVEY, due: true } })
  on('classic.Stop', () => ({}))
  on('prompt.submit', (_: unknown, e: { text: string }) => ({ text: e.text }))
  await endTurn($)
  const ui = await $.ui.mount({ ...BAND, props: { ...BAND.props, isCollapsed: true }, surface: 'terminal' })
  await $.prompt.submit({ text: 'next task' })
  expect(toasts).toEqual([SORRY])
  await ui.unmount()
})

test('a due turn with the survey still open swaps in a fresh one with the newest skill', async ($, on) => {
  const survey: { due: boolean; skill: string | null; evals: typeof SURVEY.evals } = { ...SURVEY, due: true, skill: null }
  engine(on, { survey })
  on('classic.Stop', () => ({}))
  await endTurn($)
  let ui = await $.ui.mount({ ...BAND, surface: 'terminal' })
  expect(await ui.find({ key: 'rate-skill' })).toBeUndefined()
  await ui.press({ key: 'tab-1' })
  await ui.press({ key: 'good-human-satisfaction' })
  await ui.unmount()
  // A turn Claude started with no prompt from the person ends on a due turn.
  survey.skill = 'poem-creator'
  await endTurn($)
  ui = await $.ui.mount({ ...BAND, surface: 'terminal' })
  expect((await ui.find({ key: 'rate-skill' }))?.text).toContain('poem-creator')
  await ui.press({ key: 'tab-1' })
  expect((await ui.find({ key: 'good-human-satisfaction' }))?.text).toContain('[ ]')
  await ui.unmount()
})

test('a question the model asks takes the band first', async ($, on) => {
  engine(on, { survey: { ...SURVEY, due: true } })
  on('classic.Stop', () => ({}))
  await endTurn($)
  const ui = await $.ui.mount({ ...BAND, props: { ...BAND.props, hasSurvey: true }, surface: 'terminal' })
  expect(await ui.keepsBeneath()).toBe(true)
  expect(await ui.find({ key: 'send' })).toBeUndefined()
  await ui.unmount()
})

test('/ratexp:rate uses the band only where Claude Code would dock a pane', () => {
  expect(panelSite({ isFullscreen: true, columns: 110 })).toBe('band')
  expect(panelSite({ isFullscreen: true, columns: 109 })).toBe('pane')
  expect(panelSite({ isFullscreen: false, columns: 200 })).toBe('pane')
  expect(panelSite(undefined)).toBe('pane')
})

test('a turn another Stop hook keeps going opens nothing yet', async ($, on) => {
  const { runs, opened } = engine(on, { survey: { ...SURVEY, due: true } })
  on('classic.Stop', () => ({ block: 'keep working' }))
  await endTurn($)
  expect(runs.map(run => run.argv[2])).toEqual(['panel-on'])
  expect(opened).toEqual([])
})

test('a turn that is not due opens nothing', async ($, on) => {
  const { opened } = engine(on)
  on('classic.Stop', () => ({}))
  await endTurn($)
  expect(opened).toEqual([])
})

const EVAL_CONTROLS = ['good-a', 'bad-a', 'good-b', 'bad-b']
const LOCKED = ['tab-1', 'tab-2', 'tab-3', 'send']

test('past the last choice of a tab, the arrows land on the next tab, not the first', () => {
  // Claude Code's down arrow goes on to the first tab's button, its Tab to the close mark.
  expect(focusLanding(['rate-session'], 'rate-session', 'tab-0', 'tab-1', 'tab-0')).toBe('tab-1')
  expect(focusLanding(['rate-session', 'rate-skill'], 'rate-skill', undefined, 'tab-1', 'tab-0')).toBe('tab-1')
  expect(focusLanding(EVAL_CONTROLS, 'bad-b', 'tab-0', 'tab-2', 'tab-1')).toBe('tab-2')
  expect(focusLanding(['comment'], 'comment', 'tab-0', 'send', 'tab-3')).toBe('send')
})

test('before the first choice of a tab, the arrows land on that tab', () => {
  expect(focusLanding(['store-yes', 'store-no'], 'store-yes', 'skip', 'tab-3', 'tab-2')).toBe('tab-2')
})

test('within a tab, and anywhere else, the arrows go where Claude Code moves them', () => {
  expect(focusLanding(EVAL_CONTROLS, 'good-a', 'bad-a', 'tab-2', 'tab-1')).toBe('bad-a')
  expect(focusLanding(EVAL_CONTROLS, 'bad-a', 'good-b', 'tab-2', 'tab-1')).toBe('good-b')
  expect(focusLanding(EVAL_CONTROLS, 'tab-1', 'tab-2', 'tab-2', 'tab-1')).toBe('tab-2')
  expect(focusLanding(EVAL_CONTROLS, 'send', 'skip', 'tab-2', 'tab-1')).toBe('skip')
})

test('with nothing to evaluate, the arrows pass the locked tabs and Send on to Skip', () => {
  expect(focusLanding(['rate-session'], 'rate-session', 'tab-0', 'skip', 'tab-0', LOCKED)).toBe('skip')
  expect(focusLanding(['rate-session'], 'tab-0', 'tab-1', 'skip', 'tab-0', LOCKED)).toBe('skip')
  expect(focusLanding(['rate-session'], 'skip', 'send', 'skip', 'tab-0', LOCKED)).toBe('tab-0')
})

test('Enter on a ticked choice takes the tick back', async ($, on) => {
  const { runs } = engine(on)
  await $.command.run({ command: 'ratexp:rate', args: '' })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  await ui.press({ key: 'tab-1' })
  await ui.press({ key: 'good-human-satisfaction' })
  await ui.press({ key: 'good-human-satisfaction' })
  expect(await ui.find({ key: 'good-human-satisfaction' })).toBeDefined()
  await ui.press({ key: 'send' })
  expect(sent(runs)).toBeUndefined()
  await ui.unmount()
})

test('with nothing to evaluate, the other tabs and Send are struck through and do nothing', async ($, on) => {
  const { runs } = engine(on)
  await $.command.run({ command: 'ratexp:rate', args: '' })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  await ui.press({ key: 'tab-1' })
  await ui.press({ key: 'good-human-satisfaction' })
  await ui.press({ key: 'tab-0' })
  await ui.press({ key: 'rate-session' })
  for (const title of ['Evals', 'Store', 'Comment', 'Send']) {
    expect((await ui.find({ type: 'Text', text: title }))?.props.strikethrough).toBe(true)
  }
  expect((await ui.find({ type: 'Text', text: 'Eval what' }))?.props.strikethrough).toBe(false)
  await ui.press({ key: 'tab-2' })
  expect(await ui.find({ key: 'store-yes' })).toBeUndefined()
  await ui.press({ key: 'send' })
  expect(sent(runs)).toBeUndefined()
  await ui.press({ key: 'rate-session' })
  expect((await ui.find({ type: 'Text', text: 'Evals' }))?.props.strikethrough).toBe(false)
  await ui.unmount()
})
