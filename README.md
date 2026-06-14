# RateXp

**Drop-in feedback collection for agentic skills.** Add one line to a skill and
it asks the user for feedback - the rating (and, with consent, the full
conversation) is stored and shown on a live dashboard.

Works with any agent runtime - Claude Code, GitHub Copilot, Cursor, Codex, and
others - because the survey runs through plain HTTP and a small shell helper, not
a vendor SDK.

## How it works

```
 skill ──curl /snippet──► core ──writes──► PostgreSQL ◄──reads── app (dashboard)
        ◄── survey steps ──┘   ▲
 user answers ──POST /feedback─┘
```

- **core** is the only public service. It serves the survey *snippet* and
  ingests the feedback a skill posts back.
- **app** is the dashboard: a read-only view of the collected feedback, served
  with its own UI. The layout is responsive - on phones the feedback table
  reflows into a stack of labelled cards. The dashboard is a real-time
  **preview**: it shows only the latest entries and the most-rated skills (both
  capped by `list_view_limit` / `top_skills_limit` in `app/app-be/config.yaml`,
  default 10 each). To pull more, use the SQL filter and **Download JSON**, which
  exports: with no query, the 10 most recent rows; for a query that returns a
  single skill, *all* of that skill's rows; for a query spanning several skills,
  the 10 most recent. So to grab everything for one skill, query it (e.g.
  `SELECT * FROM feedback WHERE skill_name = '...'`) then Download JSON. The (i)
  badge next to the SQL box explains the same.

## Add it to a skill

There are no prerequisites - add one step to your `SKILL.md`. First ask the user
*"Would you like to provide your feedback?"*; only if they say **yes**, run the
command (on **no**, skip it):

```bash
curl -sS "https://<your-core-url>/snippet"
```

The snippet returns step-by-step instructions the agent follows to ask the user
for a rating and post it back. See [`examples/`](./examples/) for complete,
working `SKILL.md` files (`cheerful`).

### How often it asks

The `every=N` parameter controls how often the survey shows: the core rolls a
1-in-N dice on each call and shows the rating on roughly **1 in N** runs,
silently skipping the rest. Omitting it uses the core's configured default
(ships as ~half the runs); `every=1` always asks.

```bash
curl -sS "https://<your-core-url>/snippet?every=1"   # always ask
curl -sS "https://<your-core-url>/snippet?every=4"   # ask ~1 in 4 runs
curl -sS "https://<your-core-url>/snippet"           # default: ~half the runs
```

The dice is rolled on the server each call, so nothing else in the skill
changes. It's probabilistic, not a strict counter - it averages out to 1 in N
over many runs rather than firing on exactly every Nth run.

## Conversation transcripts (opt-in)

The survey's checklist includes *store trajectory* options - *may we store this
whole conversation to help improve the skill?* The user is told the conversation is **PII-redacted** before
storage. Only if the user picks **Yes** does a small helper script upload the
local session transcript. It's converted to **ATIF** (Agent Trajectory
Interchange Format - a standard JSON shape for an agent conversation).
On the dashboard each rating links to its conversation, which opens in a
slide-over drawer as a step-by-step timeline, with every message rendered as
formatted Markdown (headings, lists, code blocks, tables) so it's easy to read.
Saying No records just the rating, exactly as before. The dashboard's **Download
JSON** carries each row's full ATIF transcript alongside its rating, so an export
holds the complete trajectory - steps, tool calls and metrics - for the whole
result set (filtered or not).

> Transcript capture currently supports Claude Code; on other runtimes the upload
> step is skipped and the rating still works.

To keep the database and dashboard fast, a trajectory larger than
`max_transcript_bytes` (in `core/config.yaml`, default 256 KiB) is **not** stored in
full. Its bulky step-by-step conversation is dropped and replaced with a small
meta-only stub that keeps the token and step totals plus an *oversized* note; the
dashboard shows that note in the trajectory drawer. The rating itself is always stored.

### PII redaction

When redaction is enabled, core runs every uploaded transcript through **Azure AI
Language** PII detection before storing it: names, emails, phone numbers and
similar personal data in the conversation text are masked, and only the redacted
version is written to the database. Redaction is **fail-closed** - if Azure
errors, the upload is dropped rather than stored unredacted.

It's configured in `core/config.yaml` (`redaction.enabled`, `endpoint`,
`languages`). There's **no secret** - core authenticates to Azure with its
Managed Identity (Entra ID), the same passwordless way it reaches the database.
Install the extra with `pip install .[redaction]` (or build the image with
`EXTRAS="redaction"`). On Azure, set `enable_redaction = true` in Terraform to
provision the Language resource and grant core's identity access - see
[`infra/README.md`](./infra/README.md). To run locally without an Azure identity,
set `redaction.enabled: false`.

## Contributing & running locally

For anything about contributing or running the whole stack (PostgreSQL + core +
dashboard) locally, see [CONTRIBUTING.md](./CONTRIBUTING.md).

## Deploy to Azure

Two web apps + a managed PostgreSQL database, all on the cheapest working tiers,
with **passwordless** database access via Microsoft Entra ID. See
[`infra/README.md`](./infra/README.md).

## Layout

```
core/      Public service: serves /snippet, ingests feedback -> PostgreSQL
app/       Dashboard: read-only API (app-be) + React UI (app-fe), one web app
infra/     Terraform: two web apps + PostgreSQL (Entra ID auth)
examples/  Example SKILL.md files
functions/ Azure Function (Docker): timer that continuously seeds demo feedback into core (skills-consumer)
```

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
