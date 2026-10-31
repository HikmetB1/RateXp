# core

core hands out the hook script, takes back whatever the hook posts, masks anything personal,
labels each conversation, and writes the result to every destination switched on - the hook
only ever posts to the same two endpoints and never knows where the data ends up. That is true
whether it is rating one skill or the whole session; only how much of the conversation it
covers differs.

```mermaid
sequenceDiagram
    participant A as Coding agent user
    participant H as the hook script
    participant C as core
    participant D as Destinations

    Note over A,C: once, while setting up
    A->>C: GET /install.sh, which fetches /ratexp-claude.sh or /ratexp-cursor.sh
    C-->>A: the hook for that coding agent, pointing back at this core
    A->>H: saved beside the agent's settings file, its hooks added to it

    Note over H,D: then whenever the user types /ratexp or /ratexp:<skill>, and every 5th turn
    H->>C: POST /feedback (eval, rating, optional comment)
    opt user consented
        H->>C: POST /transcript (the skill's run, or the session so far)
        C->>C: rebuild the conversation, mask personal data, then label it
    end
    C->>D: write to every enabled destination
    C-->>H: 201 stored, or 503 if none accepted
```

## Quick start: install in one command

Install RateXp once in the coding agent you use - nothing to configure. As of now it works
with Claude Code and Cursor CLI.

```bash
# Pick one

# Claude Code  ->  saves ~/.claude/ratexp-claude.sh, adds its hooks to ~/.claude/settings.json
curl -fsSL https://ratexp-core.azurewebsites.net/install.sh | bash -s -- install claude

# Cursor CLI  ->  saves ~/.cursor/ratexp-cursor.sh, adds its hooks to ~/.cursor/hooks.json
curl -fsSL https://ratexp-core.azurewebsites.net/install.sh | bash -s -- install cursor
```

Everything else in the settings file stays, and a copy of the original settings file is
saved as `<file>.ratexp-backup`.

Uninstall, check the status, or install for one project? The installer's help shows how to do each:

```bash
curl -fsSL https://ratexp-core.azurewebsites.net/install.sh | bash -s -- --help
```

> [!TIP]
> Rather paste the hooks yourself? The [dashboard](https://ratexp-app.azurewebsites.net/)'s
> **Install RateXp** popup shows them. That is the whole setup; ratings land on the same
> dashboard.

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

> [!TIP]
> Want to run your own core instead of the hosted one? See
> [Custom deploy](../docs/custom-deploy.md).

## Layout: what lives in this folder

```text
core/
├── ratexp-claude.sh     the Claude Code hook: rates the session and any skill run in it
├── ratexp-cursor.sh     the same for Cursor CLI
├── install.sh           saves either hook and adds its hooks to the agent's settings
├── api/                 routes, record schemas, rate limiting, ATIF trajectory building
├── modules/
│   ├── dashboard/       the dashboards: a shared base, one file per destination, the publish command
│   ├── labeling/        labels each stored conversation with its business case, language and task type
│   ├── redaction/       masks PII before storage: the presidio or azure adapter
│   └── write/           the destinations, the fan-out, and the SQL migrations
├── tests/               core's own tests: mocked, no network or database
├── evals/               the surveys users answer, one file per eval over a shared base (see Config)
├── config.yaml          the settings below; load_config.py reads it
└── Dockerfile           builds in the docs site and every optional adapter (config alone picks which adapters run)
```

## Running locally: start it on your machine

From the repo root, this puts core on <http://localhost:8000>, beside PostgreSQL and the
dashboard:

```bash
docker compose up --build -d
```

Compose mounts this folder, so edits reload in place and each hook is re-read per request.
core also serves the docs site at `/guide/`; which copy it serves is in
[docs-server](../docs-server/README.md#running-locally-start-it-on-your-machine).
To run core on its own instead, you install the extras your `config.yaml` switches on
yourself - the Dockerfile installs all of them, `uv sync` installs none, and Presidio
additionally needs the per-language spaCy models the Dockerfile downloads:

```bash
uv sync --extra redaction-presidio --extra dynatrace-otlp
DATABASE_URL=postgresql://ratexp:ratexp@localhost:5432/ratexp uv run uvicorn api.serve_http:app --reload
```

To label conversations too, add `--extra labeling` and set `AZURE_OPENAI_ENDPOINT`; the model
is reached with your `az login`, which needs "Cognitive Services OpenAI User" on the account.

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
  `label` (no commas) and `description` for its `good` and its `bad` answer. Each file is laid
  over [`evals/base.yaml`](./evals/base.yaml), which holds what every eval shares - the True and
  False labels - so an eval writes only what differs, and its own value wins. Copy the base to
  start a new eval; `base` itself is never one. A rating keeps only the eval's name, so a survey
  that asks something new needs a new name. Baked into the hooks core serves, so users
  re-download the hook to get a new or reworded eval
- `redaction`: whether personal data is masked and which adapter does it - `presidio`
  (in-process, free) or `azure` (AI Language, billed per 1,000 records). Both are in the
  image, so switching is one value plus a restart, never a rebuild
- `labeling`: gives each stored conversation one word per group in `labels` - its
  `business_case`, main `language` and `task_type` - picked by the Azure OpenAI
  `deployment` from a digest of the masked conversation cut to `max_input_chars`. The
  groups are fixed (each is a column and an attribute); the words in each list are yours.
  It never blocks a save: labeling off, no endpoint, an oversized stub, or a model that
  fails or takes longer than `timeout_seconds` leaves the labels empty
- `write_adapters`: the destinations every submission is written to. They are independent -
  one failing is logged and never blocks the others - but the request fails with `503` if
  none of them accepted. Each shapes a record its own way, as the top of its file in
  [`modules/write/adapters/`](./modules/write/adapters/) says:
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
- `AZURE_OPENAI_ENDPOINT`: the Azure OpenAI account `labeling` calls, named in
  `config.yaml`; unset skips labeling. Leave it unset under compose: the container has no
  Azure identity to call it with
- `DT_TENANT_URL` / `DT_ACCESS_TOKEN`, `CUSTOM_PSQL_DSN`, `CUSTOM_DT_TENANT_URL` /
  `CUSTOM_DT_TOKEN`, `BLUEBOX_OTLP_ENDPOINT` / `BLUEBOX_OTLP_TOKEN`,
  `PHOENIX_COLLECTOR_ENDPOINT` / `PHOENIX_API_KEY` / `PHOENIX_PROJECT_NAME`: one group per
  destination, named (never valued) in `config.yaml`. A destination missing its value is
  skipped with a warning instead of failing
- `DT_QUERY_URL` / `DT_DASHBOARD_TOKEN`: the apps host and token the Dynatrace dashboard is
  published with, read only by `modules/dashboard/publish_to_dynatrace.py` (its docstring
  gives the scopes), never by the running service

## Tests: how to run them

```bash
uv sync --extra test --extra dynatrace-otlp && uv run pytest
```

Mocked, so no network or database. They also drive the hooks and the installer themselves with a fake curl.
Without `dynatrace-otlp` the Dynatrace writer tests skip quietly.

## Deploy: how it gets to Azure

core is one of the two web apps in the Terraform stack - see
[Deploy to Azure](../docs/custom-deploy.md#deploy-to-azure-from-zero-to-live). The Dynatrace
dashboard goes out by hand: `publish_to_dynatrace.py` in
[`modules/dashboard/`](./modules/dashboard/) says how to run it.
