# Contributing to RateXp

## Table of contents
- [Running locally](#running-locally)
- [Configuration](#configuration)
  - [Environment variables](#environment-variables)
  - [`core/config.yaml`](#coreconfigyaml)
  - [`app/config.yaml`](#appconfigyaml)
  - [`seeder/config.yaml`](#seederconfigyaml)
- [The hook script](#the-hook-script)
- [Deploy to Azure](#deploy-to-azure)
- [Tests](#tests)
- [Repository layout](#repository-layout)
- [TODO](#todo)
- [Contributor License Agreement](#contributor-license-agreement)

## Running locally

**Prerequisite:** Docker with Docker Compose **v2** (the `docker compose` command, with a space).

### 1. Start the stack
The whole stack - PostgreSQL + core + dashboard - comes up with one command:

```bash
git clone <repo-url> ratexp && cd ratexp
cp core/.env.example core/.env  # only to send feedback somewhere besides PostgreSQL
docker compose up --build -d
```

| Service | URL                     | What it is                                          |
|---------|-------------------------|-----------------------------------------------------|
| core    | <http://localhost:8000> | serves `/ratexp.sh`, ingests `/feedback` + `/transcript` |
| app     | <http://localhost:8001> | the dashboard                                       |

Handy commands: `docker compose logs -f core` follows a service's logs, and
`docker compose down -v` stops everything and wipes the data.

### 2. Send your own ratings (optional)
Install a test skill using the [quick start](./README.md#quick-start---ship-ratexp-with-your-skill),
then launch Claude Code with your local core and a survey on every run:

```bash
RATEXP_URL=http://localhost:8000 RATEXP_EVERY=1 claude
```

Local skills under `.claude/skills/` are gitignored.

### 3. Seed demo feedback (optional)
To auto-fill the dashboard with realistic demo feedback, run the seeder. It needs
an LLM, so put that model's key (e.g. `OPENAI_API_KEY`) in `seeder/.env`, then bring
it up with the `seed` profile (kept out of a plain run because it spends API credits):

```bash
cp seeder/.env.example seeder/.env   # set the key for the model in seeder/config.yaml
docker compose --profile seed up --build -d
```

## Configuration
Settings come from two places:
- **`config.yaml`** - non-secret tunables, per service. Every key is required; a
  missing key fails loudly at startup, so the file is the single source of truth.
- **Environment variables** - secrets and per-environment wiring.

### Environment variables

Locally every environment variable has a working default (the stack runs as-is). On
Azure, Terraform sets the database wiring plus core's `RATEXP_PUBLIC_URL` /
`RATEXP_REDACTION_PROVIDER` / `DT_TENANT_URL` / `DT_ACCESS_TOKEN`, the dashboard's
`DT_QUERY_URL` / `DT_ACCESS_TOKEN`, and the seeder's `MODEL` / `RATEXP_CORE_URL` /
`SEED_SCHEDULE`.

Each service keeps its own values: `core/.env` holds the tenant URLs, DSNs and
tokens core writes to; `app/.env` holds the dashboard's read source; `seeder/.env`
holds the seeder's model key. All three are gitignored, each with an `.env.example`
beside it. Stack wiring (ports, `DATABASE_URL`, `RATEXP_PUBLIC_URL`) has working
defaults in [`docker-compose.yml`](./docker-compose.yml); to override one, put it in
a root `.env`, which compose reads automatically.

Two groups you supply by hand:

- The **custom / Bluebox destinations**, and only for the adapters you enable
  yourself - `CUSTOM_PSQL_DSN`, `CUSTOM_DT_TENANT_URL`, `CUSTOM_DT_TOKEN`,
  `BLUEBOX_OTLP_ENDPOINT`, `BLUEBOX_OTLP_TOKEN` in `core/.env`, and
  `CUSTOM_DT_QUERY_URL` in `app/.env` for the read side. Terraform never sets
  these; an adapter whose value is missing is skipped with a warning.
- The **optional demo seeder**, and only if you choose to run it - it needs an LLM.
  You pick which one in [`seeder/config.yaml`](./seeder/config.yaml); `seeder/.env`
  holds only that model's credentials:

| Variable                | Required when…                        | What to put                                            |
|-------------------------|---------------------------------------|--------------------------------------------------------|
| `OPENAI_API_KEY`        | `model` starts `openai:`              | your OpenAI key                                        |
| `AZURE_OPENAI_ENDPOINT` | `model` starts `azure_openai:`        | your Azure OpenAI endpoint (with `OPENAI_API_VERSION`) |
| `AZURE_OPENAI_API_KEY`  | `azure_openai:`, no Managed Identity  | your Azure OpenAI key (optional if using Managed Identity) |



### `core/config.yaml`
*Where to set:* [`core/config.yaml`](./core/config.yaml).

| Key                     | Default     | Meaning                                                          |
|-------------------------|-------------|------------------------------------------------------------------|
| `schema_version`        | `ATIF-v1.7` | ATIF version stamped on every stored transcript                  |
| `max_body_bytes`        | `5242880`   | Largest accepted request body (guards `/transcript`)            |
| `max_transcript_bytes`  | `262144`    | Largest trajectory stored in full; bigger ones keep a meta-only stub |
| `rate_limit_per_minute` | `120`       | Per-IP request budget (`0` disables the limiter)                 |
| `default_survey_every`  | `2`         | Ask on every Nth run; baked into distributed hooks. `RATEXP_EVERY` overrides it. |

#### Redaction

Masks PII before storage (see [`core/modules/redaction/`](./core/modules/redaction/)).

| Key                       | Meaning                                                                 |
|---------------------------|-------------------------------------------------------------------------|
| `redaction.enabled`       | Turn redaction on. Set here and nowhere else — both adapters are already in the image. |
| `redaction.provider`      | `presidio` (in-process, free) or `azure` (Language account). `RATEXP_REDACTION_PROVIDER` overrides — cloud sets it from Terraform's `redaction_provider`. |
| `redaction.languages`     | PII model languages; the first is the fallback.                         |
| `redaction.azure_endpoint`| Language account endpoint — only for the `azure` provider.              |

The cloud image ships both adapters, so flipping provider is one setting + a restart (no rebuild).

#### Write destinations (`write_adapters.*`)

Each submission is written to **every** adapter whose `enabled` is true — independent of one another (one failing is logged and never blocks the others), and the submission counts as accepted once **at least one** takes it; if none do, core answers `503`. See [`core/modules/write/adapters/`](./core/modules/write/adapters/) + [`core/modules/write/dispatch_to_adapters.py`](./core/modules/write/dispatch_to_adapters.py). This is the *write* side (many destinations); the *read* side — where the dashboard reads back from — is the single enabled `read_adapters` source whose filter box speaks its own language, documented under [`app/config.yaml`](#appconfigyaml) below.

| Adapter            | Where it writes                              | Connection (env var named in config)          |
|--------------------|----------------------------------------------|-----------------------------------------------|
| `app_be_psql`      | RateXp's DB — the live dashboard reads it     | `DATABASE_URL` / `RATEXP_DB_AUTH`             |
| `custom_psql`      | An adopter's own PostgreSQL                   | DSN from `dsn_env`                            |
| `app_be_dynatrace` | RateXp's Dynatrace tenant (OTLP)              | URL from `tenant_url_env`, token from `token_env` |
| `custom_dynatrace` | An adopter's own Dynatrace tenant (OTLP)      | URL from `tenant_url_env`, token from `token_env` |
| `bluebox`          | A Bluebox workspace (OTLP) — **write-only**   | URL from `endpoint_env`, token from `token_env` |

- **No secrets or URLs in this file** — only the *names* of the env vars that hold them.
- **Missing values are safe** — an adapter enabled but without its tenant/token/DSN is skipped with a warning.
- **Nothing to install** — every adapter's dependencies are already in the image; enabling one here is the whole step.
- **Bluebox takes either URL form** — the full OTLP base, or a bare tenant URL.
- **Bluebox is write-only** — no query language, so no read adapter; read it with `bluebox ask`.
- **Cloud values** — `app_be_dynatrace` gets `DT_TENANT_URL` / `DT_ACCESS_TOKEN` from Terraform's `dynatrace_tenant_url` / `dynatrace_access_token`.

### `app/config.yaml`
*Where to set:* [`app/config.yaml`](./app/config.yaml).

| Key                        | Default     | Meaning                                       |
|----------------------------|-------------|-----------------------------------------------|
| `schema_version`           | `ATIF-v1.7` | ATIF version expected on stored transcripts   |
| `list_view_limit`          | `10`        | Rows the dashboard shows by default           |
| `list_max_limit`           | `1000`      | Hard ceiling on any single response           |
| `top_skills_limit`         | `10`        | Skills shown in the "Top skills" panel        |
| `query_enabled`            | `true`      | Turn the read-only filter box (SQL or DQL) on/off |
| `query_timeout_ms`         | `5000`      | Per-query statement timeout                   |
| `query_max_rows`           | `1000`      | Hard cap on rows a filter/JSON export returns |
| `ws_enabled`               | `true`      | Turn the live-updates WebSocket on/off        |
| `ws_broadcast_interval_ms` | `2000`      | How often the live feed checks for changes    |

#### Read source (`read_adapters`)

The dashboard reads from **one** source ([`app/modules/read/`](./app/modules/read/)) — the one with `enabled: true` in `read_adapters` (like the write side's `enabled` flags, but **exactly one** may be on). It **mirrors the write side's 2×2** (RateXp's own vs. a custom adopter store × PostgreSQL vs. Dynatrace). Like the write side, the choice lives only in `config.yaml`, so changing it needs a rebuild. The dashboard's **filter box speaks that source's own query language** — SQL for PostgreSQL, DQL for Dynatrace — which the adapter validates + row-caps + runs read-only. The UI learns the language from `GET /meta`.

| Source             | Query lang. | Reads from                               | Settings (env var named in config)                          |
|--------------------|-------------|------------------------------------------|-------------------------------------------------------------|
| `app_be_psql`      | **SQL**     | RateXp's own database                    | uses the dashboard's `DATABASE_URL` / `RATEXP_DB_AUTH`      |
| `custom_psql`      | **SQL**     | An adopter's own PostgreSQL              | `dsn_env` (their connection string)                        |
| `app_be_dynatrace` | **DQL**     | RateXp's Dynatrace tenant (fanned-out logs) | `query_url_env` (apps/DQL host), `token_env` (needs `storage:logs:read`) |
| `custom_dynatrace` | **DQL**     | An adopter's Dynatrace tenant            | `query_url_env` (apps/DQL host), `token_env`               |

- **The `*_psql` sources are the full experience** — transcripts, top-skills, the live feed, and a SQL filter box.
- **The `*_dynatrace` sources** read the fanned-out logs; the filter box then accepts DQL. Transcripts come back **truncated** (the `ratexp.atif` attribute is capped on ingest), and each read is an async DQL query (slower/costlier than SQL). See [`modules/read/adapters/read_from_dynatrace.py`](./app/modules/read/adapters/read_from_dynatrace.py).
- **No secrets or URLs in this file** — only env var *names*. For the Dynatrace sources, `query_url_env` must point at the **apps/DQL** host (e.g. `…apps.dynatrace.com`), not the ingest host.
- **Cloud values** — the app gets `DT_QUERY_URL` / `DT_ACCESS_TOKEN` from Terraform's `dynatrace_query_url` / `dynatrace_access_token`, used only when `config.yaml` has a Dynatrace source enabled (RateXp's deployment reads its own store — `app_be_psql` or `app_be_dynatrace`; the `custom_*` sources are for adopters wiring their own).

### `seeder/config.yaml`
*Where to set:* [`seeder/config.yaml`](./seeder/config.yaml) (demo seeder only).

| Key                | Default                 | Meaning                                                       |
|--------------------|-------------------------|---------------------------------------------------------------|
| `schema_version`   | `ATIF-v1.7`             | ATIF version stamped on every seeded trajectory (matches core's) |
| `model`            | `openai:gpt-4o-mini`    | LangChain `init_chat_model` id; env `MODEL` overrides it      |
| `core_url`         | `http://localhost:8000` | Core to submit to; env `RATEXP_CORE_URL` overrides it         |
| `temperature`      | `0.7`                   | Sampling temperature for the agent                            |
| `max_rounds`       | `40`                    | Agent turns per task before it must rate                      |
| `interval_seconds` | `3`                     | Pause between runs, local loop only (Azure uses `SEED_SCHEDULE`) |
| `critical_ratio`   | `0.3`                   | Share of runs that take the tough-reviewer stance (0–1)       |
| `oversized_ratio`  | `0.2`                   | Share of runs whose trajectory is bloated past the limit (0–1)|
| `system_prompt`, `task_prompt`, `critical_prompt` | – | The agent's instructions               |

## The hook script
[`core/ratexp.sh`](./core/ratexp.sh) runs from skill frontmatter:

| Event | Purpose |
|-------|---------|
| `UserPromptExpansion` | Count a slash-command invocation |
| `PreToolUse` (`Skill\|AskUserQuestion`) | Count a Skill invocation or validate the survey |
| `Stop` | Request the survey on a sampled run |
| `PostToolUse` (`AskUserQuestion`) | Send feedback and a consented transcript |
| `PostToolUseFailure` (`AskUserQuestion`) | Close a failed survey |

The hook uses Bash 3.2+, curl, and standard macOS/Linux utilities. Per-session state
lives under `${XDG_STATE_HOME:-~/.local/state}/ratexp`. Uploads are limited to 4 MiB
and require consent from the matching tool response.

After editing the script or `default_survey_every`, regenerate its template and
example copies:

```bash
python3 core/tools/sync_hooks.py
python3 core/tools/sync_hooks.py --check
```

Copies use the hosted core URL and configured survey frequency. `GET /ratexp.sh`
renders the same script using the server's `RATEXP_PUBLIC_URL`. Users can override
these settings with `RATEXP_URL` and `RATEXP_EVERY`.

## Deploy to Azure
The provided deployment is **Azure-based**. One Terraform stack builds everything -
two web apps (`core` + `app`), a managed PostgreSQL server, and a container registry, with **passwordless** database access via Microsoft
Entra ID (no DB secrets to manage).

**Prerequisites:**

- Azure CLI (run `az login` first)
- Terraform
- Docker

```bash
cd infra
cp terraform.tfvars.example terraform.tfvars   # set subscription_id
terraform init && terraform apply              # create the Azure resources

# build + push the two images
az acr login --name "$(terraform output -raw acr_name)"
docker build -t "$(terraform output -raw core_image)" ../core && docker push "$(terraform output -raw core_image)"
docker build -t "$(terraform output -raw app_image)" --build-arg EXTRAS=entra -f ../app/Dockerfile ../app && docker push "$(terraform output -raw app_image)"
```

Grant the app identities database access using
[`infra/grant-db-access.sql`](./infra/grant-db-access.sql), then stop and start each
app to load the pushed image. Azure's `restart` keeps the cached image.
`terraform output` provides the app names, identity IDs, and service URLs.

Optional tfvars enable redaction (`enable_redaction`) and the demo seeder
(`enable_seeder`).

## Tests
There are two layers. **Per-service** tests are fast and mocked - no network or
database needed:

```bash
(cd core && uv sync --extra test && uv run pytest)                       # core
(cd app && uv sync --extra test && uv run pytest)                 # dashboard API
(cd seeder && uv sync --extra test && uv run pytest)              # demo seeder
```

Core's tests also exercise the hook with a fake curl and check that all shipped
scripts and skill frontmatter are consistent.

**Whole-app** tests in `tests/` check the services working together over HTTP - core
writes feedback, the dashboard reads it back:

| File | Checks |
|------|--------|
| `test_smoke.py` | Both services answer `/healthz`; core serves `/ratexp.sh` with its URL baked in and accepts a `/feedback` post. |
| `test_end_to_end.py` | A rating (and a consented trajectory) posted to core appears on the dashboard and in its top-skills stats; the last test drives the *shipped* hook script itself, so the exact bytes a real skill puts on the wire are the ones checked. |
| `test_azure_live.py` | Opt-in smoke test against the deployed Azure web apps (skipped by default). |

Bring the stack up first:

```bash
docker compose up --build -d
uv run --no-project --with pytest --with httpx pytest tests/
```

If the stack isn't running, these skip with a hint. They default to the compose ports
(`8000`/`8001`); point elsewhere with `RATEXP_CORE_URL` / `RATEXP_APP_URL`.

An opt-in smoke test can also hit the **deployed Azure apps** (skipped by default).
Enable it by supplying their URLs:

```bash
export RATEXP_AZURE_LIVE=1
export RATEXP_AZURE_CORE_URL=https://<your-core>.azurewebsites.net
export RATEXP_AZURE_APP_URL=https://<your-app>.azurewebsites.net
pytest tests/test_azure_live.py
```

## Repository layout

```text
.
├── core/                Public FastAPI service: serves the hook script (/ratexp.sh), ingests feedback → PostgreSQL
│   ├── ratexp.sh        The canonical hook, source of every shipped copy
│   ├── tools/           Dev-only, never shipped: sync_hooks.py regenerates the hook copies
│   ├── api/             The HTTP surface: routes, record schemas, trajectory building
│   ├── modules/
│   │   ├── redaction/   PII masking: presidio (in-process) or azure (AI Language)
│   │   └── write/       Write destinations (each submission goes to every enabled one) + the SQL schema
│   ├── template/        Copy-and-fill starting points: skill/ and plugin/
│   └── examples/        The same poem skill packaged both ways, hooks already wired
├── app/                 Dashboard FastAPI service: read-only API; also serves the UI
│   ├── api/             The HTTP surface: routes, record schemas, snapshots, the live feed
│   ├── modules/
│   │   └── read/        Read sources - the dashboard reads from the one enabled source
│   ├── FE/              React dashboard (source)
│   └── Dockerfile       Builds the app image (UI bundled in)
├── seeder/              Optional Azure Function: a timer has an agent use a skill, then rate it
│   ├── azure_function/  The timer trigger + host.json; the Dockerfile flattens it into the image root
│   ├── api/             One run end to end, and the two ways one gets started
│   ├── modules/
│   │   ├── agent/       The model, the skill pool, and the sandboxed run itself
│   │   └── submit/      Messages → ATIF, and the two posts to core
│   └── skills/          The skills the agent picks from (third-party, see ATTRIBUTION.md)
├── infra/               Terraform stack for Azure (two web apps + PostgreSQL)
├── assets/              Images the README shows (banner, demo GIF, dashboard shot)
├── tests/               Whole-app integration tests (run against a live/local stack)
├── docker-compose.yml   Local stack: PostgreSQL + core + app (+ opt-in seed profile)
├── CONTRIBUTING.md      This file
├── THIRD_PARTY_NOTICES.md  Licenses and citations for projects RateXp builds on
├── CLA.md / LICENSE     Contributor agreement and license
└── pyproject.toml       Shared Python tooling config
```

`core/`, `app/` and `seeder/` are each self-contained - they deliberately duplicate
small helpers (database connection, config loading) so any one of them can be built
and deployed on its own.

## TODO

- [ ] Expand to more coding agents (e.g. GitHub Copilot)
- [ ] Fix truncated trajectories when the dashboard reads from Dynatrace: a very large `atif` exceeds Dynatrace's per-attribute storage cap, so it's truncated on ingest → invalid JSON → the read adapter returns an empty stub (`dynatrace_truncated`) → the trajectory viewer shows nothing (PostgreSQL still shows it in full). Fix by shipping transcripts to Dynatrace as **one log line per step** (each step's text fits the content field, avoiding the single-attribute cap), and/or surface `dynatrace_truncated` in the UI ("full copy in PostgreSQL"). Normal-sized transcripts are unaffected.
- [ ] Build a Dynatrace dashboard (over the fanned-out `ratexp.*` logs) so ratings and trajectories can be viewed natively in Dynatrace — not just through RateXp's own dashboard reading via DQL. Open question from earlier: dashboard vs. a Dynatrace App.

## Contributor License Agreement

Before your contribution can be merged, you agree to the
[Contributor License Agreement](./CLA.md). You accept it automatically by
submitting a pull request; sign your commits with `git commit -s` (adds a
`Signed-off-by` line) to confirm. In short: you keep your own rights, but you
grant the owner a license to your contribution - including the right to
relicense it later.