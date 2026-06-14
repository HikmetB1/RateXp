# Contributing

Thanks for helping improve RateXp. This guide covers running the project,
testing it, and every setting you can change. For what RateXp *is* and how to
embed it in a skill, see the [README](./README.md).

## Prerequisites

- [Docker](https://www.docker.com/) + Docker Compose **v2** (the `docker compose`
  command, with a space - the older hyphenated `docker-compose` v1 is not supported)
- [uv](https://docs.astral.sh/uv/) (Python tooling) - for running a service or
  the tests directly
- [Node.js](https://nodejs.org/) 22+ - only for frontend work

## Run it locally

First, clone the repo and enter it (run all commands below from this root):

```bash
git clone <repo-url> ratexp
cd ratexp
```

The whole stack (PostgreSQL + core + app) then comes up with one command:

```bash
cp .env.example .env           # optional - defaults work out of the box
docker compose up --build -d
docker compose logs -f core    # follow a service
docker compose down -v         # stop and wipe data
```

| Service | URL                     | What it is                   |
|---------|-------------------------|------------------------------|
| core    | <http://localhost:8000> | snippet + feedback ingestion |
| app     | <http://localhost:8001> | the dashboard                |

```bash
curl -sS "http://localhost:8000/snippet"   # what a skill fetches
```

`core` mounts its source and runs with `--reload`, so backend edits there take
effect without a rebuild (`prompt/prompt.md` is read per request - no restart
needed). API docs (OpenAPI/Swagger) are at <http://localhost:8000/docs>.

### Run a single service with live reload

Handy when iterating on `app-be` or running outside Docker. Point
`DATABASE_URL` at the compose database (or any PostgreSQL):

```bash
cd app/app-be
uv sync --extra test
DATABASE_URL=postgresql://ratexp:ratexp@localhost:5432/ratexp \
  uv run uvicorn server:app --reload --port 8001
```

### Frontend with hot reload

The dashboard is bundled into the `app` image, so `docker compose up` already
serves it. For live UI editing, run the Vite dev server and point it at the
running API:

```bash
cd app/app-fe
npm install
VITE_API_BASE=http://localhost:8001 npm run dev   # http://localhost:5173
```

### Seed demo feedback (skills-consumer)

`functions/skills-consumer/` deploys as an Azure Function (timer trigger; see
[infra/README.md](infra/README.md#optional-demo-feedback-seeder-skills-consumer), where it
uses Azure OpenAI passwordlessly via Managed Identity), but locally it runs as a plain script
that continuously fills RateXp with realistic **agentic** feedback: each run a LangChain agent
loads one bundled skill, does a small task with it, then submits a score, a comment, and (with
consent) the transcript. With the stack already up, point it at `core` and let it run
(`Ctrl-C` to stop):

```bash
cd functions/skills-consumer
cp .env.example .env           # set MODEL + the matching key
uv run --no-project --with-requirements requirements.txt seeder.py
```

Or bring it up with the rest of the stack via the opt-in `seed` profile (left out of a
plain `docker compose up` because it spends API credits):

```bash
docker compose --profile seed up --build -d
```

Either way it logs a line per run (`seeded skill=handoff feedback=True transcript=True`);
watch the results land on the dashboard and stop it when done. Its settings are in the
[configuration reference](#configuration-reference) (`skills-consumer` rows, plus
`functions/skills-consumer/config.yaml`). Add a skill by dropping a `skills/<name>/SKILL.md`
- no code changes (credits in `skills/ATTRIBUTION.md`).

## Tests

Real tests, no network or database needed (the database layer is stubbed).

```bash
cd core && uv sync --extra test && uv run pytest                   # core
cd app/app-be && uv sync --extra test && uv run pytest             # dashboard API
cd functions/skills-consumer && uv sync --extra test && uv run pytest  # demo seeder
```

Lint and format with [ruff](https://docs.astral.sh/ruff/):

```bash
uvx ruff check core/ app/app-be/
uvx ruff format core/ app/app-be/
```

CI (`.github/workflows/ci.yml`) runs lint, both test suites, the frontend build,
and the Docker builds on every push and pull request.

## Configuration reference

Settings come from two places:

- **`config.yaml`** - non-secret tunables, per service. Every key is required; a
  missing key fails loudly at startup, so the file is the single source of truth.
- **Environment variables** - secrets and per-environment wiring. Never put
  secrets in `config.yaml` or git.

### Environment variables

| Variable              | Service     | Default                         | Meaning                                                            |
|-----------------------|-------------|---------------------------------|--------------------------------------------------------------------|
| `DATABASE_URL`        | core, app   | local compose DB                | PostgreSQL connection string (no password in `entra` mode)         |
| `RATEXP_DB_AUTH`      | core, app   | `password`                      | `password` (local) or `entra` (Managed Identity token, cloud)      |
| `RATEXP_SUBMIT_URL`   | core        | `http://localhost:8000/feedback`| Baked into `/snippet` so skills know where to POST feedback        |
| `RATEXP_ENV`          | app         | `local`                         | `prod` requires `RATEXP_CORS_ORIGINS`                              |
| `RATEXP_CORS_ORIGINS` | app         | empty (`*` locally)             | Comma-separated allowlist of browser origins                       |
| `VITE_API_BASE`       | app-fe      | `http://localhost:8001`         | API base baked into the UI at build time (`""` = same origin)      |
| `MODEL`               | skills-consumer | `openai:gpt-4o-mini`        | LangChain `init_chat_model` id; selects the provider               |
| `OPENAI_API_KEY`      | skills-consumer | -                           | Key when `MODEL` starts with `openai:`                             |
| `AZURE_OPENAI_ENDPOINT`| skills-consumer | -                          | Azure OpenAI endpoint when `MODEL` starts with `azure_openai:` (with `OPENAI_API_VERSION`) |
| `AZURE_OPENAI_API_KEY`| skills-consumer | -                           | Optional Azure key; if unset the seeder auths passwordlessly with its Managed Identity (the deployed function's path) |
| `RATEXP_CORE_URL`     | skills-consumer | `http://localhost:8000`     | RateXp core the seeder POSTs feedback to                           |
| `SEED_SCHEDULE`       | skills-consumer | `*/3 * * * * *`             | Deployed Azure timer cadence (NCRONTAB); ignored by the local script |

### `core/config.yaml`

| Key                     | Default     | Meaning                                            |
|-------------------------|-------------|----------------------------------------------------|
| `schema_version`        | `ATIF-v1.7` | ATIF version stamped on every stored transcript    |
| `max_body_bytes`        | `5242880`   | Largest accepted request body (guards `/transcript`)|
| `rate_limit_per_minute` | `120`       | Per-IP request budget (`0` disables the limiter)   |
| `default_survey_every`  | `2`         | Default `?every=N` sampling when a `/snippet` call omits it (`1` = always ask) |

### `app/app-be/config.yaml`

| Key                        | Default     | Meaning                                              |
|----------------------------|-------------|------------------------------------------------------|
| `schema_version`           | `ATIF-v1.7` | ATIF version expected on stored transcripts          |
| `list_view_limit`          | `10`        | Rows the dashboard shows by default                  |
| `list_max_limit`           | `1000`      | Hard ceiling on any single response                  |
| `top_skills_limit`         | `10`        | Skills shown in the "Top skills" panel               |
| `query_enabled`            | `true`      | Turn the read-only SQL filter box on/off             |
| `query_timeout_ms`         | `5000`      | Per-query statement timeout                          |
| `query_max_rows`           | `1000`      | Hard cap on rows a filter/JSON export returns        |
| `ws_enabled`               | `true`      | Turn the live-updates WebSocket on/off               |
| `ws_broadcast_interval_ms` | `2000`      | How often the live feed checks for changes           |

### `functions/skills-consumer/config.yaml`

| Key                | Default                 | Meaning                                          |
|--------------------|-------------------------|--------------------------------------------------|
| `model`            | `openai:gpt-4o-mini`    | Same id as `MODEL`; env `MODEL` overrides it     |
| `temperature`      | `0.7`                   | Sampling temperature for the agent               |
| `max_rounds`       | `40`                    | Agent turns per task before it must rate         |
| `interval_seconds` | `3`                     | Pause between runs for the local script (Azure uses `SEED_SCHEDULE` instead) |
| `core_url`         | `http://localhost:8000` | Core URL; env `RATEXP_CORE_URL` overrides it     |
| `system_prompt`, `task_prompt` | -          | The agent's instructions                         |

## Database

`core` owns the schema and applies migrations at startup; `app` only reads (in
the cloud it runs with a read-only database role). Add a migration by dropping a
new numbered file in `core/migrations/` (e.g. `003_add_thing.sql`) - it's applied
once, in order, and recorded in the `schema_version` table.

### Auth modes

- **`password`** (local): the password comes from `DATABASE_URL`.
- **`entra`** (cloud): no password is stored. The web app's Managed Identity
  fetches a Microsoft Entra ID token and uses it as the password (`db.py`). Build
  the image with the `entra` extra (`--build-arg EXTRAS=entra`) so `azure-identity`
  is installed. Setup is wired by [`infra/`](./infra/README.md).

## Repository layout

```text
.
├── core/         Public FastAPI service: serves the snippet, writes to PostgreSQL
├── app/
│   ├── app-be/   Dashboard FastAPI service: read-only API; also serves the UI
│   └── app-fe/   React dashboard (source)
├── infra/        Terraform stack for Azure
├── examples/     Sample SKILL.md files
└── functions/    Azure Function (Docker): timer seeding demo feedback into core
```

`core/` and `app/app-be/` are each self-contained - they deliberately duplicate
small helpers (`db.py`, `config.py`) so either can be built and deployed alone.

## TODO

- [ ] Flip storage into an adapter
- [ ] Flip query into adapter-based

## Contributor License Agreement

Before your contribution can be merged, you agree to the
[Contributor License Agreement](./CLA.md). You accept it automatically by
submitting a pull request; sign your commits with `git commit -s` (adds a
`Signed-off-by` line) to confirm. In short: you keep your own rights, but you
grant the owner a license to your contribution - including the right to
relicense it later.
