# core

<!-- shared ../README.md how-ratexp-works -->
## How RateXp works: from hook to destination

See [How RateXp works](../README.md#how-ratexp-works-from-hook-to-destination) in the README.
<!-- /shared -->

<!-- shared ../README.md quick-start -->
## Quick start: install RateXp

See [Quick start](../README.md#quick-start-install-ratexp) in the README.
<!-- /shared -->

## Layout: what this folder holds

```text
core/
├── ratexp-claude.sh     the Claude Code hook script: rates the session and each skill run in the session
├── ratexp-cursor.sh     the Cursor CLI hook script: does the same as ratexp-claude.sh
├── install.sh           saves a hook script and adds the RateXp hooks to the settings of the agent
├── api/                 routes, record schemas, rate limits, the ATIF trajectory builder and the local hourly delete
├── modules/
│   ├── dashboard/       the dashboards: a shared base, one file for each destination, the publish command
│   ├── labeling/        gives each stored conversation a business case, a language and a task type
│   ├── redaction/       masks PII before storage: the presidio adapter or the azure adapter
│   └── write/           the destinations, the fan-out and the SQL migrations
├── tests/               the tests of core: mocked, with no network and no database
├── evals/               the surveys that users answer: one file for each eval, over a shared base (see Config)
├── config.yaml          the settings below; load_config.py reads config.yaml
├── retention_function/  the hourly timer of the retention Function, its host.json and its dependencies
├── Dockerfile           builds in the docs site and all optional adapters (config.yaml selects the adapters that run)
└── Dockerfile.retention builds the image of the retention Function: the Azure Functions base, the code of core, the timer
```

## Run locally: start core on your machine

To start core on <http://localhost:8000>, with PostgreSQL and the dashboard, run this command
from the repo root:

```bash
docker compose up --build -d
```

- **Live reload:** Compose mounts the `core/` folder. core reloads when you save a file, and
  core reads the hook scripts again for each request.
- **Docs site:** core also serves the docs site at `/guide/`. For the copy of the docs site
  that core serves, see [docs-server](../docs-server/README.md#run-locally-start-docs-server-on-your-machine).

To run core without compose, install the extras that your `config.yaml` switches on:

- **Dockerfile:** The Dockerfile installs all extras.
- **`uv sync`:** `uv sync` installs no extras.
- **Presidio:** Presidio also needs the spaCy model of each language. The Dockerfile downloads
  the spaCy models.

```bash
uv sync --extra redaction-presidio --extra dynatrace-otlp
DATABASE_URL=postgresql://ratexp:ratexp@localhost:5432/ratexp uv run uvicorn api.serve_http:app --reload
```

To label conversations, also add `--extra labeling` and set `AZURE_OPENAI_ENDPOINT`. core
connects to the model with your `az login`. Your account needs the "Cognitive Services OpenAI
User" role on the Azure OpenAI account.

The web app of core never deletes old ratings. To delete old ratings on your machine, start
the opt-in `retention` profile:

- **When:** The `retention` service deletes one time at start, then one time each hour.
- **Where:** The `retention` service deletes from each destination that has the `retention`
  switch on in `core/config.yaml`. The `app_be_psql` destination is the database of the stack.
- **Credentials:** `core/.env` gives each destination its credentials.

Run this command from the repo root:

```bash
docker compose --profile retention up --build -d
```

## Config: every key in config.yaml

Each key in [`config.yaml`](./config.yaml) is necessary. If a key is missing, core stops at
startup with an error.

- `schema_version`: The ATIF version that core writes on each stored transcript.
- `max_body_bytes`: The largest request body that core accepts, in bytes. The limit protects
  `/transcript`. If a body is larger, core returns `413` and keeps nothing, not even a stub.
  Thus, set `max_body_bytes` higher than `max_transcript_bytes`. The hook script never sends
  more than 4 MiB in one request.
- `max_transcript_bytes`: The largest trajectory that core stores in full. For a larger
  trajectory, core stores only a stub with the metadata. Thus, a small number of very large
  conversations cannot make the database too large.
- `rate_limit_per_minute`: The number of requests that one IP address can send in one minute.
  `0` switches the rate limit off.
- `default_survey_every`: The number of turns between two session ratings (the N in "every Nth
  turn"). core writes the number into the hook scripts that core serves. `RATEXP_EVERY` on the
  machine of the user overrides the number.
- `default_survey_eval`: The eval that RateXp asks every Nth turn, and on a `/ratexp` command
  without an eval name. The value is the name of one file in [`evals/`](./evals/).
  - **Eval file:** Each file in `evals/` is one eval. The file name is the word that users type
    after `/ratexp`.
  - **`question`:** The question of the eval. core replaces `{subject}` with the session or
    with the skill.
  - **`label` and `description`:** The label (with no commas) and the description of the `good`
    answer and of the `bad` answer.
  - **Base file:** core puts each eval file over [`evals/base.yaml`](./evals/base.yaml). The
    base file holds the values that all evals share: the True and False labels. An eval file
    holds only the values that are different. A value in the eval file wins over the value in
    the base file.
  - **New eval:** To start a new eval, copy the base file. `base` itself is never an eval.
  - **New question:** A rating keeps only the name of the eval. Thus, a survey with a new
    question needs a new name.
  - **Hook update:** core writes the evals into the hook scripts that core serves. Thus, users
    must download the hook script again to get a new or a changed eval.
- `redaction`: Switches the masks for personal data on or off, and selects the adapter:
  `presidio` (in-process, free) or `azure` (AI Language, billed for each 1,000 records). The
  image contains both adapters. To change the adapter, change one value and restart core. You
  do not have to build the image again.
- `labeling`: core gives each stored conversation one word from each group in `labels`:
  `business_case`, the main `language` and `task_type`.
  - **Model:** The Azure OpenAI `deployment` selects the words from a digest of the masked
    conversation. core cuts the digest to `max_input_chars`.
  - **Groups and words:** The groups are fixed, because each group is a column and an
    attribute. You select the words in each list.
  - **Empty labels:** Labeling never stops a save. The labels stay empty in these cases:
    labeling is off, the endpoint is not set, the conversation is an oversized stub, or the
    model fails or takes longer than `timeout_seconds`.
- `retention`: How many of the newest ratings a destination keeps.
  - **`keep_newest`:** The number of the newest ratings that each destination keeps when the
    `retention` switch of the destination is on.
  - **Deletion:** The destination also keeps the conversations from the same time span, and
    deletes the older ratings and conversations permanently, one time each hour.
  - **Who deletes:** The retention Function deletes (`retention_function/`). The web app of core
    never deletes. On your machine, the opt-in `retention` profile in Run locally deletes.
  - **Between two runs:** A destination can hold the ratings of up to one hour more than
    `keep_newest`.
- `write_adapters`: The destinations that core writes each submission to. The destinations are
  independent: core logs a failure of one destination and continues with the other
  destinations. If no destination accepts the submission, the request fails with `503`. Each
  adapter makes a different record, as the top of each file in
  [`modules/write/adapters/`](./modules/write/adapters/) tells:
  - `app_be_psql`, `custom_psql`: one table row
  - `app_be_dynatrace`, `custom_dynatrace`, `bluebox`: one OTLP log line
  - `phoenix`: one span
  - **`retention` switch:** `app_be_psql`, `custom_psql` and `phoenix` each have a `retention`
    switch (see `retention`). With the switch on, `phoenix` deletes each old trace in its
    project. Thus, give RateXp a Phoenix project of its own. The OTLP destinations never
    delete.

## Env: the secrets core reads

`core/.env` holds the secrets and the settings that change for each environment
([example](./.env.example)):

- `DATABASE_URL` / `RATEXP_DB_AUTH`: The PostgreSQL database that `app_be_psql` writes to, and
  how core authenticates: `password` on your machine, `entra` (Managed Identity) on Azure.
- `RATEXP_PUBLIC_URL`: The base URL that core writes into the hook scripts that core serves.
  With the base URL, the hook scripts send the data back to the correct core. A hook script
  that you copy directly from the `core/` folder has no URL and sends no data.
- `RATEXP_REDACTION_PROVIDER`: Overrides `redaction.provider` for one deployment.
- `AZURE_OPENAI_ENDPOINT`: The Azure OpenAI account that `labeling` calls. `config.yaml` names
  `AZURE_OPENAI_ENDPOINT`. If `AZURE_OPENAI_ENDPOINT` is not set, core does not label conversations. Do not set
  `AZURE_OPENAI_ENDPOINT` under compose, because the container has no Azure identity to call the account.
- `DT_TENANT_URL` / `DT_ACCESS_TOKEN`, `CUSTOM_PSQL_DSN`, `CUSTOM_DT_TENANT_URL` /
  `CUSTOM_DT_TOKEN`, `BLUEBOX_OTLP_ENDPOINT` / `BLUEBOX_OTLP_TOKEN`,
  `PHOENIX_COLLECTOR_ENDPOINT` / `PHOENIX_API_KEY` / `PHOENIX_PROJECT_NAME`: One group for each
  destination. `config.yaml` names each variable, but never holds the value. If a destination
  has no value, core skips the destination with a warning and does not fail.
- `OTEL_RESOURCE_ATTRIBUTES`: The OpenTelemetry attributes on each record that core writes to
  Dynatrace and Bluebox. Set `deployment.environment.name=prod` or
  `deployment.environment.name=dev` there. A record without `deployment.environment.name`
  counts as `prod`. Terraform sets the value on Azure. For the Dynatrace views of each
  environment, see [View options](../docs/read-the-feedback.md#view-options-where-to-see-the-human-evals).
- `DT_QUERY_URL` / `DT_DASHBOARD_TOKEN`: The apps host and the token to publish the Dynatrace
  dashboard. Only `modules/dashboard/publish_to_dynatrace.py` reads `DT_QUERY_URL` and
  `DT_DASHBOARD_TOKEN`, and the docstring of `publish_to_dynatrace.py` gives the scopes. The
  running core service never reads `DT_QUERY_URL` or `DT_DASHBOARD_TOKEN`.

## Tests: how to run them

```bash
uv sync --extra test --extra dynatrace-otlp && uv run pytest
```

- **Mocked:** The tests use no network and no database. The tests also run the hook scripts
  and the installer, with a fake `curl`.
- **Dynatrace tests:** Without `dynatrace-otlp`, pytest skips the Dynatrace writer tests and
  shows no error.

## Deploy: how core gets to Azure

- **core:** core is one of the two web apps in the Terraform stack. See
  [Deploy to Azure](../docs/custom-deploy.md#deploy-to-azure-from-zero-to-live).
- **Retention Function:** `Dockerfile.retention` builds the retention Function from this
  folder. For the deploy steps of the retention Function, see
  [Deploy to Azure](../docs/custom-deploy.md#deploy-to-azure-from-zero-to-live).
- **Dynatrace dashboard:** You publish the Dynatrace dashboard manually. The docstring of
  `publish_to_dynatrace.py` in [`modules/dashboard/`](./modules/dashboard/) tells how.
