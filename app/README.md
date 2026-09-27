# app

app is the dashboard: it shows the feedback core has stored. It can read that feedback from
five different places - RateXp's PostgreSQL or your own, RateXp's Dynatrace or your own, or an
Arize Phoenix project. Each one is a "read adapter", and you switch exactly one on. The filter
box then uses whatever query language that place speaks: SQL for PostgreSQL, DQL for Dynatrace,
`key:value` filters for Phoenix.

## Layout: what lives in this folder

```text
app/
├── api/                 routes, record schemas, snapshot building, the live feed
├── modules/
│   └── read/            the one source the dashboard reads back from, one adapter each
├── FE/                  the React dashboard: src/, public/, vite.config.js
├── tests/               the app's own tests: mocked, no database
├── config.yaml          the settings below; load_config.py reads it
└── Dockerfile           stage 1 builds FE/, stage 2 runs the API with the bundle inside
```

## Running locally: start it on your machine

From the repo root, this puts the dashboard on <http://localhost:8001>:

```bash
docker compose up --build -d
```

That image serves the *built* bundle, so every UI edit needs a rebuild. While working on the
UI, run Vite beside it instead and get live reload - it serves on <http://localhost:5173> and
calls the API on `:8001`:

```bash
cd FE && npm install && npm run dev
```

## Config: every key in config.yaml

[`config.yaml`](./config.yaml) - every key is required, a missing one fails at startup:

- `schema_version`: ATIF version expected on stored transcripts (matches core's)
- `core_url`: the core the install popup tells users to install from
- `list_view_limit` / `list_max_limit`: rows the list endpoints return by default, and the
  hard ceiling on any one response
- `top_skills_limit`: how many skills the "Top skills" panel shows
- `query_enabled` / `query_timeout_ms` / `query_max_rows`: the filter box; `false` turns the
  endpoint off, the other two cap how long a query runs and how much it returns
- `ws_enabled` / `ws_broadcast_interval_ms`: the live feed; `false` turns it off, the interval
  is how often it checks for new data
- `read_adapters`: which single source the dashboard reads from. It mirrors core's write side
  but is single-select - enable **exactly one**. The choice lives only here, so switching
  source means editing this file and rebuilding. The `*_dynatrace` sources return transcripts
  truncated, because the attribute they arrive in is capped on ingest; `phoenix` sorts rows
  and counts the top skills in the dashboard, because its API can do neither

## Env: the secrets it reads

Secrets and per-environment wiring, in `app/.env` ([example](./.env.example)):

- `DATABASE_URL` / `RATEXP_DB_AUTH`: the PostgreSQL the `*_psql` sources read, and how to
  authenticate - `password` locally, `entra` (Managed Identity) on Azure
- `DT_QUERY_URL` / `DT_ACCESS_TOKEN`, `CUSTOM_PSQL_DSN`, `CUSTOM_DT_QUERY_URL` /
  `CUSTOM_DT_TOKEN`: one group per source, named (never valued) in `config.yaml`. A
  `*_QUERY_URL` must point at the apps/DQL host, not the ingest host, and its token needs the
  `storage:logs:read` scope
- `PHOENIX_COLLECTOR_ENDPOINT` / `PHOENIX_API_KEY` / `PHOENIX_PROJECT_NAME`: the same three
  the Phoenix destination is written with, because the dashboard reads the same project back
- `RATEXP_CORE_URL`: overrides `core_url`, so each deployment's install popup points at its
  own core without editing the file
- `RATEXP_ENV` / `RATEXP_CORS_ORIGINS`: `local` (the default) allows any origin; any other
  value makes `RATEXP_CORS_ORIGINS` mandatory and the app refuses to start without it

## Tests: how to run them

```bash
uv sync --extra test && uv run pytest
```

Mocked, so no database is needed - the read adapters are stubbed and the live feed is driven
by hand.

## Deploy: how it gets to Azure

app is one of the two web apps in the Terraform stack - see
[Deploy to Azure](../CONTRIBUTING.md#deploy-to-azure-from-zero-to-live).
