# Contributing to RateXp

## Table of contents
- [Running locally](#running-locally)
- [Configuration](#configuration)
  - [Environment variables](#environment-variables)
  - [`core/config.yaml`](#coreconfigyaml)
  - [`app/app-be/config.yaml`](#appapp-beconfigyaml)
  - [`functions/skills-consumer/config.yaml`](#functionsskills-consumerconfigyaml)
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
cp .env.example .env          # optional - defaults work out of the box
docker compose up --build -d
```

| Service | URL                     | What it is                      |
|---------|-------------------------|---------------------------------|
| core    | <http://localhost:8000> | MCP server (`/mcp`) + ingestion |
| app     | <http://localhost:8001> | the dashboard                   |

Handy commands: `docker compose logs -f core` follows a service's logs, and
`docker compose down -v` stops everything and wipes the data.

### 2. Send your own ratings (optional)
To watch ratings land on the dashboard, point a project `.mcp.json` at your local
core:

```json
{
  "mcpServers": {
    "ratexp": { "type": "http", "url": "http://localhost:8000/mcp" }
  }
}
```

Then add a feedback step to that skill's `SKILL.md`:

```md
## Feedback step

Call the `feedback` tool on the **ratexp** MCP server with `every: 1`, then
follow the instructions it returns.
```

### 3. Seed demo feedback (optional)
To auto-fill the dashboard with realistic demo feedback, run the seeder. It needs
an LLM, so set `MODEL` and the matching key (e.g. `OPENAI_API_KEY`) in
`functions/skills-consumer/.env`, then bring it up with the `seed` profile (kept
out of a plain run because it spends API credits):

```bash
cp functions/skills-consumer/.env.example functions/skills-consumer/.env  # set MODEL + key
docker compose --profile seed up --build -d
```

## Configuration
Settings come from two places:
- **`config.yaml`** - non-secret tunables, per service. Every key is required; a
  missing key fails loudly at startup, so the file is the single source of truth.
- **Environment variables** - secrets and per-environment wiring.

### Environment variables

Locally every environmetnal variable value has a working default (the stack runs as-is); on Azure, Terraform sets them all for you.

The only variables you supply by hand are for the **optional demo seeder**,
and only if you choose to run it - it needs an LLM, so you give it a model and the
matching key in `functions/skills-consumer/.env`:

| Variable                | Required when…             | What to put                                            |
|-------------------------|----------------------------|--------------------------------------------------------|
| `MODEL`                 | always (for the seeder)    | LangChain model id, e.g. `openai:gpt-4o-mini`          |
| `OPENAI_API_KEY`        | `MODEL` starts `openai:`   | your OpenAI key                                        |
| `AZURE_OPENAI_ENDPOINT` | `MODEL` starts `azure_openai:` | your Azure OpenAI endpoint (with `OPENAI_API_VERSION`) |
| `AZURE_OPENAI_API_KEY`  | `azure_openai:`, no Managed Identity | your Azure OpenAI key (optional if using Managed Identity) |



### `core/config.yaml`
*Where to set:* [`core/config.yaml`](./core/config.yaml).

| Key                     | Default     | Meaning                                                          |
|-------------------------|-------------|------------------------------------------------------------------|
| `schema_version`        | `ATIF-v1.7` | ATIF version stamped on every stored transcript                  |
| `max_body_bytes`        | `5242880`   | Largest accepted request body (guards `/transcript`)            |
| `rate_limit_per_minute` | `120`       | Per-IP request budget (`0` disables the limiter)                 |
| `default_survey_every`  | `2`         | Default `every` when a `feedback` MCP call omits it (`1` = always)|

> Redaction keys (`redaction.enabled`, `redaction.provider` — `presidio` or `azure`, `redaction.languages`, and `redaction.azure_endpoint` for the azure provider). See [`core/redaction_adapters/`](./core/redaction_adapters/). `redaction.enabled` here is the default; the `RATEXP_REDACTION_ENABLED` env var overrides it per environment — the local stack sets it `false`, while the cloud sets nothing and so uses this file's `true`. Likewise `RATEXP_REDACTION_PROVIDER` overrides `redaction.provider` (the cloud sets it from Terraform's `redaction_provider`), so you can flip provider by changing one setting and restarting core — no rebuild, since the cloud image ships both adapters.

### `app/app-be/config.yaml`
*Where to set:* [`app/app-be/config.yaml`](./app/app-be/config.yaml).

| Key                        | Default     | Meaning                                       |
|----------------------------|-------------|-----------------------------------------------|
| `schema_version`           | `ATIF-v1.7` | ATIF version expected on stored transcripts   |
| `list_view_limit`          | `10`        | Rows the dashboard shows by default           |
| `list_max_limit`           | `1000`      | Hard ceiling on any single response           |
| `top_skills_limit`         | `10`        | Skills shown in the "Top skills" panel        |
| `query_enabled`            | `true`      | Turn the read-only SQL filter box on/off      |
| `query_timeout_ms`         | `5000`      | Per-query statement timeout                   |
| `query_max_rows`           | `1000`      | Hard cap on rows a filter/JSON export returns |
| `ws_enabled`               | `true`      | Turn the live-updates WebSocket on/off        |
| `ws_broadcast_interval_ms` | `2000`      | How often the live feed checks for changes    |

### `functions/skills-consumer/config.yaml`
*Where to set:* [`functions/skills-consumer/config.yaml`](./functions/skills-consumer/config.yaml) (demo seeder only).

| Key                | Default                 | Meaning                                                       |
|--------------------|-------------------------|---------------------------------------------------------------|
| `model`            | `openai:gpt-4o-mini`    | Same id as `MODEL`; env `MODEL` overrides it                  |
| `temperature`      | `0.7`                   | Sampling temperature for the agent                            |
| `max_rounds`       | `40`                    | Agent turns per task before it must rate                      |
| `interval_seconds` | `3`                     | Pause between runs for the local script                       |
| `core_url`         | `http://localhost:8000` | Core URL; env `RATEXP_CORE_URL` overrides it                  |
| `critical_ratio`   | `0.3`                   | Share of runs that take the tough-reviewer stance (0–1)       |
| `oversized_ratio`  | `0.2`                   | Share of runs whose trajectory is bloated past the limit (0–1)|
| `system_prompt`, `task_prompt`, `critical_prompt` | – | The agent's instructions               |

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
docker build -t "$(terraform output -raw core_image)" --build-arg EXTRAS=entra ../core && docker push "$(terraform output -raw core_image)"
docker build -t "$(terraform output -raw app_image)" --build-arg EXTRAS=entra -f ../app/Dockerfile ../app && docker push "$(terraform output -raw app_image)"
```

Then grant each app its database role and start the apps (use **stop/start**, not
restart) - those exact commands, plus optional features (`enable_redaction`,
`enable_seeder`), are in [`infra/README.md`](./infra/README.md). The dashboard and
core URLs come back as Terraform outputs (`app_url`, `core_url`).

## Tests
There are two layers. **Per-service** tests are fast and mocked - no network or
database needed:

```bash
cd core && uv sync --extra test && uv run pytest                       # core
cd app/app-be && uv sync --extra test && uv run pytest                 # dashboard API
cd functions/skills-consumer && uv sync --extra test && uv run pytest  # demo seeder
```

**Whole-app** tests in `tests/` check the services working together over HTTP - core
writes feedback, the dashboard reads it back:

| File | Checks |
|------|--------|
| `test_smoke.py` | Both services answer `/healthz`; core advertises its MCP tools. |
| `test_end_to_end.py` | Feedback submitted via core's MCP tools appears on the dashboard and in its top-skills stats, and a stored trajectory reads back through the dashboard. |
| `test_azure_live.py` | Opt-in smoke test against the deployed Azure web apps (skipped by default). |

Bring the stack up first:

```bash
docker compose up --build -d
uv run --no-project --with pytest --with httpx pytest tests/
```

If the stack isn't running, these skip with a hint instead of failing. They default
to the compose ports (`8000`/`8001`); point elsewhere with `RATEXP_CORE_URL` /
`RATEXP_APP_URL`.

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
├── core/                Public FastAPI service: hosts the MCP server (/mcp), ingests feedback → PostgreSQL
├── app/
│   ├── app-be/          Dashboard FastAPI service: read-only API; also serves the UI
│   ├── app-fe/          React dashboard (source)
│   └── Dockerfile       Builds the app image (UI bundled in)
├── infra/               Terraform stack for Azure (two web apps + PostgreSQL)
├── examples/            Sample SKILL.md files (each with its .mcp.json)
├── template/            Copy-and-fill SKILL.md + .mcp.json for a new skill
├── functions/
│   └── skills-consumer/ Azure Function: timer that seeds demo feedback into core
├── tests/               Whole-app integration tests (run against a live/local stack)
├── docker-compose.yml   Local stack: PostgreSQL + core + app (+ opt-in seed profile)
├── COMPREHENSIVE.md     Full project guide
├── CONTRIBUTING.md      This file
├── CITATION.md          Citations for the projects RateXp builds on
├── CLA.md / LICENSE     Contributor agreement and license
└── pyproject.toml       Shared Python tooling config
```

`core/` and `app/app-be/` are each self-contained - they deliberately duplicate small
helpers (`db.py`, `config.py`) so either can be built and deployed on its own.

## TODO

- [ ] Flip storage into an adapter
- [ ] Flip query into adapter-based
- [ ] Expand to more coding agents (e.g. GitHub Copilot)

## Contributor License Agreement

Before your contribution can be merged, you agree to the
[Contributor License Agreement](./CLA.md). You accept it automatically by
submitting a pull request; sign your commits with `git commit -s` (adds a
`Signed-off-by` line) to confirm. In short: you keep your own rights, but you
grant the owner a license to your contribution - including the right to
relicense it later.