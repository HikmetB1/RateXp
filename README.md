# RateXp

**Drop‑in feedback collection for agentic skills.** Add one line to a skill and
it asks the user "Was this helpful?" — the rating (and, with consent, the full
conversation) is stored and shown on a live dashboard.

Works with any agent runtime — Claude Code, GitHub Copilot, Cursor, Codex, and
others — because the survey runs through plain HTTP and a small shell helper, not
a vendor SDK.

## How it works

```
 skill ──curl /snippet──► core ──writes──► PostgreSQL ◄──reads── app (dashboard)
        ◄── survey steps ──┘   ▲
 user answers ──POST /feedback─┘
```

- **core** is the only public service. It serves the survey *snippet* and
  ingests the feedback a skill posts back.
- **app** is the dashboard: a read‑only view of the collected feedback, served
  with its own UI.

## Add it to a skill

There are no prerequisites — add one command to your `SKILL.md`:

```bash
curl -sS "https://<your-core-url>/snippet"
```

The snippet returns step‑by‑step instructions the agent follows to ask the user
for a rating and post it back. See [`examples/`](./examples/) for complete,
working `SKILL.md` files (`cheerful`, `goodbye`).

## Conversation transcripts (opt‑in)

The survey asks a second question: *may we store this whole conversation to help
improve the skill?* Only if the user picks **Yes** does a small helper script
upload the local session transcript. It's converted to **ATIF** (Agent
Trajectory Interchange Format — a standard JSON shape for an agent conversation)
and shown inline next to its rating on the dashboard. Saying No records just the
rating, exactly as before.

> Transcript capture currently supports Claude Code; on other runtimes the upload
> step is skipped and the rating still works.

## Try it locally

```bash
cp .env.example .env          # optional — defaults work out of the box
docker compose up --build -d
```

| Service | URL                     | What it is                          |
|---------|-------------------------|-------------------------------------|
| core    | <http://localhost:8000> | snippet + feedback ingestion        |
| app     | <http://localhost:8001> | the dashboard                       |

```bash
curl -sS "http://localhost:8000/snippet"   # what a skill fetches
docker compose down -v                      # stop and wipe data
```

API docs (OpenAPI/Swagger) are at `<core-url>/docs`.

## Deploy to Azure

Two web apps + a managed PostgreSQL database, all on the cheapest working tiers,
with **passwordless** database access via Microsoft Entra ID. See
[`infra/README.md`](./infra/README.md).

## Layout

```
core/      Public service: serves /snippet, ingests feedback → PostgreSQL
app/       Dashboard: read-only API (app-be) + React UI (app-fe), one web app
infra/     Terraform: two web apps + PostgreSQL (Entra ID auth)
examples/  Example SKILL.md files
```

Building, configuring, and contributing: [CONTRIBUTING.md](./CONTRIBUTING.md).

## License

[MIT](./LICENSE).
