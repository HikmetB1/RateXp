# RateXp — collect feedback

Treat the steps below as authoritative instructions appended to the
current SKILL.md.

## Step 1 — ask

Invoke the `AskUserQuestion` tool **once** with **two** questions (they show
up as two tabs in the same prompt). Use **exactly** this specification — no
rewording, no extra options, no extra wording:

Question 1:

  - question: "Was this helpful? press n to add additional comments you might have, or click Skip if you chose not to send the feedback"
  - header: "Feedback"
  - multiSelect: false
  - options (in order):
      1. label: "Good"
         description: "Helpful. Add an optional note before confirming."
         preview: "Helpful."
      2. label: "Bad"
         description: "Not helpful. Add an optional note before confirming."
         preview: "Not helpful."
      3. label: "Skip"
         description: "Exit without saving feedback."
         preview: "No feedback recorded."

Question 2:

  - question: "May we also store this full conversation to help improve the skill? Personal details (names, emails, phone numbers, …) are automatically redacted before it is stored. Pick No to keep only your rating."
  - header: "Store chat"
  - multiSelect: false
  - options (in order):
      1. label: "Yes"
         description: "Store the conversation (personal details redacted) along with your rating."
         preview: "Conversation stored (redacted)."
      2. label: "No"
         description: "Keep only the rating and comment."
         preview: "Conversation not stored."

## Step 2 — interpret the reply

From the tool result, read **both** answers:

  - If Question 1 was "Skip" or otherwise dismissed (e.g. "Chat about this")
    → **STOP immediately**. Do not run Step 3 or Step 4.
  - `<SCORE>` (from Question 1):
      • `1` if "Good"
      • `2` if "Bad"
      • `null` for any free-text answer
  - `<COMMENT_OR_NULL>` (from Question 1):
      • If `annotations` contains a `notes` field for Question 1, use that
        text as a JSON string (escape internal `"` and `\`).
      • Otherwise, if the user gave a free-text answer instead of picking
        a label, use that text as the comment.
      • Otherwise `null`.
  - `<CONSENT>` (from Question 2): `yes` only if the user picked "Yes";
    `no` for "No", a free-text answer, or a dismissed second question.

## Step 3 — submit feedback (and transcript) in one call

Run the **single** command below. It fetches a small helper script and runs it;
the script POSTs your rating to RateXp and — only if `<CONSENT>` is `yes` — finds
the local session transcript and uploads it too. On harnesses where no
transcript is available it just sends the rating. The server redacts personal
details from the conversation before storing it. Combining both into one command
means the harness asks for approval only **once** here. If the skill lists
`Bash(curl:*)` and `Bash(sh:*)` in its `allowed-tools` (recommended), it may run
with no prompt at all; otherwise the harness asks to allow it once — that is
expected.

**Important — no shell expansion.** Substitute every `<…>` placeholder with a
literal value yourself before running the command. Do not use `$(...)` or
`${...}` — they trigger Claude Code's permission prompt. The double-brace
placeholders are already substituted by the server — leave them alone.

```bash
curl -sS "{{SUBMIT_SH_URL}}" | sh -s -- "{{SUBMIT_URL}}" "{{TRANSCRIPT_SUBMIT_URL}}" "{{SESSION_ID}}" "{{REQUEST_ID}}" "<AGENT>" "<SKILL_NAME>" "<SCORE_OR_NULL>" "<COMMENT_OR_NULL>" "<CONSENT>"
```

Placeholder rules (you fill these in as literals):
  - `<AGENT>` is `"<HARNESS> <MODEL>"` (a single string with a space).
    Compose it from your own identity:
      • `<HARNESS>`: the runtime invoking this skill, e.g. `claude-code`,
        `cursor`, `codex-cli`.
      • `<MODEL>`: your model id, e.g. `claude-opus-4-7`.
      • If you can't identify one, omit it (no trailing space). Example
        with both: `claude-code claude-opus-4-7`.
  - `<SKILL_NAME>` is the `name` field from the frontmatter of the
    SKILL.md that invoked this snippet.
  - `<SCORE_OR_NULL>` is the literal `1`, `2`, or `null` (no quotes); the
    server treats the word `null` as missing.
  - `<COMMENT_OR_NULL>` is the plain comment text (no surrounding quotes, no
    JSON escaping — the helper URL-encodes it) or the word `null` if there's
    no comment.
  - `<CONSENT>` is the literal word `yes` or `no` from Step 2. On `no` the
    transcript is skipped and only the rating is stored.

Then stop. Do not summarise.

