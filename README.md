# RateXp
<p align="center">
  <img src="./assets/banner.png" alt="RateXp - user based skill feedback" width="720">
</p>

## One-line pitch
Hey, skill author 👋 - shipped a skill and wondering how it's actually used? RateXp is a feedback collection solution for agentic skills - ship your skill with RateXp by pairing your `SKILL.md` with an MCP client pointing to our core (see [Quick start](#quick-start---ship-your-skill-with-ratexp) below) and it asks users for a rating (and, with consent, the full conversation), redacts it, and shows it on a [live dashboard](https://ratexp-app.azurewebsites.net/).

## Demo
<p align="center">
  <img src="./assets/demo.gif" alt="RateXp demo - collecting feedback and showing it on the dashboard" width="720">
</p>

## The problem defintion
Once you ship a skill, you're flying blind - there's no easy way to see how it's actually used or to hear back from the people using it. Authors get no ratings, no real conversations, and nothing concrete to improve the skill with, unless they build their own feedback plumbing from scratch.

## What is RateXp
RateXp is a feedback collection solution for agentic skills that closes that gap. A skill author pairs their `SKILL.md` with an MCP client pointing to our core (`.mcp.json`) and adds a short feedback step; when the skill runs, the agent calls RateXp's MCP tools to collect a quick rating and - only with consent - upload the whole conversation. The answer is sent to RateXp, which strips out personal info before saving it, and anyone can open a live dashboard to watch the feedback arrive - giving authors user ratings plus the actual material they need to improve the skill.

## Who it's for
For individual skill authors and organizations alike - anyone who's shipped an agentic skill and wants user ratings plus the actual conversations to see how satisfied their users are and improve it.

## Features
1. **Quick MCP setup** - point an `.mcp.json` at your core and add a short feedback step to your `SKILL.md`.
2. **Tested models** - works over the Model Context Protocol; tested and working with Claude Opus (4.8, 4.7, 4.6, 4.5) and Sonnet (4.6, 4.5).
3. **Ratings + comments** - quick good/bad rating with an optional comment from the user.
4. **Opt-in transcripts** - with the user's consent, stores the whole conversation in a standard format (ATIF) for review.
5. **PII redaction** - personal info is masked before storage via a pluggable adapter (self-hosted Presidio or Azure AI Language), fail-closed (drops rather than saves unredacted).
6. **Adjustable sampling** - `every=N` controls how often the survey shows, so you don't nag every run.
7. **Live dashboard** - read-only view of feedback as it arrives, with a SQL filter and JSON export.
8. **Responsive UI** - the table reflows into cards on phones.

## How it works

```mermaid
sequenceDiagram
    participant U as user
    participant S as skill (agent)
    participant H as upload helper<br/>(user's machine)
    participant C as core (MCP + HTTP)
    participant R as redaction<br/>(Presidio / Azure AI Language)
    participant DB as PostgreSQL
    participant A as dashboard API<br/>(read-only)
    participant D as dashboard UI

    S->>C: feedback tool
    C-->>S: survey steps (~1 in N) or "skip"
    S->>U: ask survey (AskUserQuestion)
    U->>S: answers (rating, consent, comment)
    S->>C: submit_feedback (rating, over MCP)
    C->>DB: write rating

    Note over S,H: only on consent
    S->>H: run curl|sh (one local command, single approval)
    H->>C: GET /upload_transcript.sh
    C-->>H: helper script
    H->>C: POST /transcript (raw .jsonl, plain HTTP)
    C->>R: redact PII (fail-closed)
    R-->>C: masked text
    C->>DB: write transcript
    Note over DB: rating + transcript linked by request_id

    D->>A: GET /snapshot (initial load, HTTP)
    A->>DB: read
    A-->>D: snapshot
    D->>A: subscribe /ws (WebSocket)
    A-->>D: live snapshots (on connect, then on change)
```

In plain words: a skill author pairs their `SKILL.md` with a small `.mcp.json`
pointing at **core**, and adds a short feedback step. When the skill runs, the
agent calls core's `feedback` MCP tool, follows the survey steps to ask the user a
quick rating (only ~1 in N runs - the rest are skipped), and sends it back through
the `submit_feedback` tool. With consent, the agent runs one command that fetches a
tiny helper from core; the helper runs **on the user's machine** and uploads the raw
conversation straight to core over plain HTTP - never through the model's context.
Core **redacts any personal info** (via Presidio or Azure AI Language, fail-closed -
it drops rather than stores anything unredacted) before saving. The **dashboard** is
a separate read-only service that reads the database and pushes live updates, so
anyone can watch the feedback arrive.

## Quick start - ship your skill with RateXp
No prerequisites - setting up feedback takes just two tiny steps (two small files):

1. Add an `.mcp.json` at your **project root** pointing at your core's MCP endpoint:

```json
{
  "mcpServers": {
    "ratexp": { "type": "http", "url": "https://<your-core-url>/mcp" }
  }
}
```

2. Add this block to your `SKILL.md` where the feedback should take place:

```md
## Feedback step

Call the `feedback` tool on the **ratexp** MCP server with `every: 1`, then
follow the instructions it returns.
```

That's the whole setup. Copy [`template/`](./template/) to start from a ready-made
skill + `.mcp.json`.

## How often it asks
`every` sets how often the survey pops up. On each call the `feedback` tool rolls a
dice and asks about **1 in N** times, skipping the rest. Use `every: 1` to ask
every time, a larger number to ask less often, or omit it for the server default
(~half the runs).

## Examples
See [`examples/poem-creator/`](./examples/poem-creator/) for a complete, working `SKILL.md`
(plus its `.mcp.json`). It asks for a mood, writes a short original poem, and then runs
the feedback step - a good template to copy and adapt. For a blank starting point, copy
[`template/`](./template/).

## The dashboard
The [dashboard](https://ratexp-app.azurewebsites.net/) is a read-only, real-time view of the feedback as it arrives. It shows
only the latest entries and the most-rated skills (both capped by `list_view_limit` / `top_skills_limit` in `app/app-be/config.yaml`, default 10 each). The layout is responsive. Each rating that has a stored conversation links to it; the transcript opens in a slide-over drawer as a step-by-step timeline, rendered as formatted Markdown.

To pull more than the preview shows, use the **SQL filter** and **Download JSON**:

- No query → the 10 most recent rows.
- A query that returns a single skill → *all* of that skill's rows.
- A query spanning several skills → the 10 most recent.

So to grab everything for one skill, query it (e.g. `SELECT * FROM feedback WHERE
skill_name = '...'`) then Download JSON. The export carries each row's full ATIF
transcript alongside its rating.

## Contact
Very glad to be in contact - reach me by [email](mailto:hikmet.beyoglu@hotmail.com) or on [LinkedIn](https://www.linkedin.com/in/hikmetb/).


## Acknowledgements and citations
We're grateful to the open-source projects that RateXp leveraged; for their licenses and formal citations see [THIRD_PARTY_NOTICES.md](./THIRD_PARTY_NOTICES.md).

## License

[PolyForm Shield 1.0.0](./LICENSE) - source-available.

Use RateXp for **any purpose, commercial included**: gather feedback about your
skills, deploy your own instance, build it into a paid skill or product. The one
limit is **no competing**: you may not use RateXp to offer a product that
competes with RateXp itself or with anything Hikmet Beyoglu provides using it
(for example, reselling it as a rival rating/feedback service) - even for free.

Anyone who passes on the software must keep the `Required Notice:` credit line
from the [LICENSE](./LICENSE). The software comes **as is, with no warranty**.
Questions: Hikmet Beyoglu (hikmet.beyoglu@hotmail.com).
