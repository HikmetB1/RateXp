# core

core hands out the hook script, takes back whatever the hook posts, masks anything personal,
and writes the result to every destination switched on - the hook only ever posts to the same
two endpoints and never knows where the data ends up. That is true whether it is rating one
skill or the whole session; only how much of the conversation it covers differs.

```mermaid
sequenceDiagram
    participant A as Coding agent user
    participant H as the hook script
    participant C as core
    participant D as Destinations

    Note over A,C: once, while setting up
    A->>C: GET /ratexp-claude.sh or /ratexp-cursor.sh
    C-->>A: the hook for that coding agent, pointing back at this core
    A->>H: saved in ~/.claude/ or ~/.cursor/, its hooks pasted into the agent's settings

    Note over H,D: then whenever the user types /ratexp or /ratexp:<skill>, and every 5th turn
    H->>C: POST /feedback (eval, rating, optional comment)
    opt user consented
        H->>C: POST /transcript (the skill's run, or the session so far)
        C->>C: rebuild the conversation, then mask personal data
    end
    C->>D: write to every enabled destination
    C-->>H: 201 stored, or 503 if none accepted
```

## Quick start: install in one command

Install RateXp once in the coding agent you use - nothing to configure. As of now it works
with Claude Code and Cursor.

```bash
# Pick one

# Claude Code  ->  saves ~/.claude/ratexp-claude.sh
curl -fsSL https://ratexp-core.azurewebsites.net/ratexp-claude.sh --create-dirs -o ~/.claude/ratexp-claude.sh

# Cursor  ->  saves ~/.cursor/ratexp-cursor.sh
curl -fsSL https://ratexp-core.azurewebsites.net/ratexp-cursor.sh --create-dirs -o ~/.cursor/ratexp-cursor.sh
```

Then paste the hooks from the [dashboard](https://ratexp-app.azurewebsites.net/)'s
**Install RateXp** popup into `~/.claude/settings.json` or `~/.cursor/hooks.json`. That is
the whole setup; ratings land on the same dashboard.

### When it asks: on /ratexp, and every 5th turn

- **The whole session** - whenever you type `/ratexp`, and every 5th turn.
- **How often** - every 5th turn by default; change `DEFAULT_EVERY` at the top of the saved
  script, or set `RATEXP_EVERY`.
- **What is stored** - only with your consent: messages, reasoning, tool calls and their
  results, with personal data masked (redacted) before it is stored.
- **One skill** - type `/ratexp:<skill>` to rate that skill's most recent run.
- **Which eval** - add an eval's name, as in `/ratexp <eval>` or `/ratexp:<skill> <eval>`;
  without one you answer the default, `human-satisfaction`. See
  [Available evals](../README.md#available-evals-what-each-one-asks).
- **Tested in** - Claude Code and Cursor CLI.

Want to run your own core instead of the hosted one? See
[CONTRIBUTING.md](../CONTRIBUTING.md#deploy-to-azure-from-zero-to-live).

## Layout: what lives in this folder

```text
core/
├── ratexp-claude.sh     the Claude Code hook: rates the session and any skill run in it
├── ratexp-cursor.sh     the same for Cursor
├── api/                 routes, record schemas, rate limiting, ATIF trajectory building
├── modules/
│   ├── redaction/       masks PII before storage: the presidio or azure adapter
│   └── write/           the destinations, the fan-out, and the SQL migrations
├── tests/               core's own tests: mocked, no network or database
├── evals/               the surveys users answer, one file per eval (see Config)
├── config.yaml          the settings below; load_config.py reads it
└── Dockerfile           builds every optional adapter in, so config alone picks what runs
```

## Running locally: start it on your machine

From the repo root, this puts core on <http://localhost:8000>, beside PostgreSQL and the
dashboard:

```bash
docker compose up --build -d
```

Compose mounts this folder, so edits reload in place and each hook is re-read per request.
To run core on its own instead, you install the extras your `config.yaml` switches on
yourself - the Dockerfile installs all of them, `uv sync` installs none, and Presidio
additionally needs the per-language spaCy models the Dockerfile downloads:

```bash
uv sync --extra redaction-presidio --extra dynatrace-otlp
DATABASE_URL=postgresql://ratexp:ratexp@localhost:5432/ratexp uv run uvicorn api.serve_http:app --reload
```

## Config: every key in config.yaml

[`config.yaml`](./config.yaml) - every key is required, a missing one fails at startup:

- `schema_version`: ATIF version stamped on every stored transcript
- `max_body_bytes`: biggest request body core accepts, in bytes - the cap that guards
  `/transcript`. A bigger one is turned away with `413` and nothing is kept, not even a stub,
  so set it higher than `max_transcript_bytes`. The hook never sends more than 4 MiB at once
- `max_transcript_bytes`: largest trajectory stored in full; a bigger one keeps only a
  meta-only stub, so a few huge conversations can't bloat the database
- `rate_limit_per_minute`: per-IP budget; `0` turns the limiter off
- `default_survey_every`: ask about the whole session every Nth turn, baked into the hooks
  core serves; `RATEXP_EVERY` on the user's machine overrides it
- `default_survey_eval`: the eval asked every Nth turn and on a `/ratexp` that names none, one
  of [`evals/`](./evals/). Each file there is one eval, named for the word users type after
  `/ratexp`: a `question` - any `{subject}` in it becomes the session or the skill - and a
  `label` (no commas) and `description` for its `good` and its `bad` answer. A rating keeps
  only the eval's name, so a survey that asks something new needs a new name. Baked into the
  hooks core serves, so users re-download the hook to get a new or reworded eval
- `redaction`: whether personal data is masked and which adapter does it - `presidio`
  (in-process, free) or `azure` (AI Language, billed per 1,000 records). Both are in the
  image, so switching is one value plus a restart, never a rebuild
- `write_adapters`: the destinations every submission is written to. They are independent -
  one failing is logged and never blocks the others - but the request fails with `503` if
  none of them accepted. Each shapes a record its own way:
  - `app_be_psql`, `custom_psql` - one table row
  - `app_be_dynatrace`, `custom_dynatrace`, `bluebox` - one OTLP log line
  - `phoenix` - one span

## Env: the secrets it reads

Secrets and per-environment wiring, in `core/.env` ([example](./.env.example)):

- `DATABASE_URL` / `RATEXP_DB_AUTH`: the PostgreSQL `app_be_psql` writes to, and how to
  authenticate - `password` locally, `entra` (Managed Identity) on Azure
- `RATEXP_PUBLIC_URL`: the base URL baked into the hooks core serves, so the hooks it hands
  out post back to the right place. A hook copied straight from this folder has no URL and
  posts nowhere
- `RATEXP_REDACTION_PROVIDER`: overrides `redaction.provider` for one deployment
- `DT_TENANT_URL` / `DT_ACCESS_TOKEN`, `CUSTOM_PSQL_DSN`, `CUSTOM_DT_TENANT_URL` /
  `CUSTOM_DT_TOKEN`, `BLUEBOX_OTLP_ENDPOINT` / `BLUEBOX_OTLP_TOKEN`,
  `PHOENIX_COLLECTOR_ENDPOINT` / `PHOENIX_API_KEY` / `PHOENIX_PROJECT_NAME`: one group per
  destination, named (never valued) in `config.yaml`. A destination missing its value is
  skipped with a warning instead of failing

## Tests: how to run them

```bash
uv sync --extra test && uv run pytest
```

Mocked, so no network or database. They also drive the hooks themselves with a fake curl.

## Deploy: how it gets to Azure

core is one of the two web apps in the Terraform stack - see
[Deploy to Azure](../CONTRIBUTING.md#deploy-to-azure-from-zero-to-live).
