# app/ratexp

app/ratexp is the RateXp web app. The RateXp app reads the data that core stored, from the one
source that `read_adapters` switches on. The RateXp app shows the data in
[two views](../../docs/read-the-feedback.md#view-options-where-to-see-the-human-evals).

- **Dashboard view:** The Dashboard view reads only from PostgreSQL.
- **Other sources:** With a source that is not PostgreSQL, the RateXp app opens on the Query &
  table view.

## Layout: what this folder holds

```text
app/ratexp/
├── api/                 routes, record schemas, snapshots, the dashboard panels, the live feed
├── modules/
│   └── read/            the one source that the dashboard reads from (one adapter for each source), and
│                        clone_dashboard_from_base.py: the panels of the Dashboard view, read from
│                        ../../core/modules/dashboard/, and the label groups, read from
│                        ../../core/config.yaml (see CONTRIBUTING.md)
├── FE/                  the React dashboard: src/{App.jsx, Dashboard.jsx, FeedbackTable.jsx, styles.js}, public/, vite.config.js
├── tests/               the tests of the app: mocked, with no database
├── config.yaml          the settings below; load_config.py reads config.yaml
└── Dockerfile           stage 1 builds FE/, stage 2 runs the API with the bundle inside
```

## Run locally: start the app on your machine

To start the dashboard on <http://localhost:8001>, run this command from the repo root:

```bash
docker compose up --build -d
```

- **Built bundle:** The image serves the built UI bundle. Thus, you must build the image again
  after each UI change.
- **Live reload:** When you work on the UI, also run Vite. Vite serves the UI on
  <http://localhost:5173>, calls the API on `:8001`, and reloads the page when you save a file.

```bash
cd FE && npm install && npm run dev
```

## Config: every key in config.yaml

Each key in [`config.yaml`](./config.yaml) is necessary. If a key is missing, the app stops at
startup with an error.

- `schema_version`: The ATIF version that the app expects on stored transcripts. The value is
  the same as in core.
- `core_url`: The core of this deployment.
- `list_view_limit` / `list_max_limit`: The default number of rows that the list endpoints
  return, and the maximum number of rows in one response. Thus, the **Feedback** table of the
  Dashboard view and of the Query & table view shows the newest `list_view_limit` ratings, and
  **Download trajectories** saves at most `list_max_limit` ratings, in both views. The download
  popup gets both values from `/meta`. The Dynatrace dashboard and the RateXp Dynatrace app get
  the same two values when they are published or synced.
- `query_enabled` / `query_timeout_ms` / `query_max_rows`: The settings of the query box.
  `false` switches the query endpoint off. The timeout and the row limit set the maximum time
  and the maximum size of one query. **Download trajectories** in the Query & table view
  (`POST /query` with `full`) reads up to `list_max_limit` rows in place of `query_max_rows`. The timeout also applies to each query of the Dashboard view.
- `ws_enabled` / `ws_broadcast_interval_ms`: The settings of the live feed. `false` switches
  the live feed off. The interval sets how often the live feed checks for new data.
- `read_adapters`: The one source that the dashboard reads from. The read adapters mirror the
  write adapters of core, but you can enable **exactly one** read adapter.
  - **Change the source:** Only `config.yaml` sets the source. To change the source, edit
    `config.yaml` and build the image again.
  - **`*_dynatrace` sources:** A `*_dynatrace` source reads a transcript from the content of a
    log. If the content of a log is not ATIF JSON, the app shows an empty trajectory.
  - **`phoenix`:** The app sorts the rows and matches each rating to its transcript. The
    Phoenix API cannot sort the rows or match a rating to its transcript.

## Env: the secrets the app reads

`app/ratexp/.env` holds the secrets and the settings that change for each environment
([example](./.env.example)):

- `DATABASE_URL` / `RATEXP_DB_AUTH`: The PostgreSQL database that the `*_psql` sources read,
  and how the app authenticates: `password` on your machine, `entra` (Managed Identity) on
  Azure.
- `DT_QUERY_URL` / `DT_ACCESS_TOKEN`, `CUSTOM_PSQL_DSN`, `CUSTOM_DT_QUERY_URL` /
  `CUSTOM_DT_TOKEN`: One group for each source. `config.yaml` names each variable, but never
  holds the value. A `*_QUERY_URL` must point to the apps (DQL) host, not to the ingest host.
  The token needs the `storage:logs:read` scope.
- `PHOENIX_COLLECTOR_ENDPOINT` / `PHOENIX_API_KEY` / `PHOENIX_PROJECT_NAME`: The same three
  variables that core uses to write to Phoenix, because the dashboard reads the same Phoenix
  project.
- `RATEXP_CORE_URL`: Overrides `core_url`. Thus, the install popup of each deployment names
  the core of that deployment, and you do not edit `config.yaml`.
- `RATEXP_ENV` / `RATEXP_CORS_ORIGINS`: With `local` (the default), the app accepts requests
  from all origins. With a different value, `RATEXP_CORS_ORIGINS` is necessary, and the app
  does not start without `RATEXP_CORS_ORIGINS`.

## Tests: how to run them

```bash
uv sync --extra test && uv run pytest
```

- **Mocked:** The tests need no database. The tests stub the read adapters and drive the live
  feed manually.

## Deploy: how the app gets to Azure

app/ratexp is one of the two web apps in the Terraform stack. See
[Deploy to Azure](../../docs/custom-deploy.md#deploy-to-azure-from-zero-to-live).
