# Config and env: where settings live

- [Files](#files-what-you-change-in-each-file)
- [Keep in mind](#keep-in-mind-settings-secrets-and-keys)

## Files: what you change in each file

| File | What you change in the file |
|---|---|
| [`core/config.yaml`](../core/config.yaml) | The destinations, redaction, labeling and its label lists, the default eval, how often RateXp asks, and the size and rate limits. See [core](../core/README.md#config-every-key-in-configyaml). |
| `core/.env` ([example](../core/.env.example)) | The database, the public URL of core, the Azure OpenAI endpoint, and the URL and token of each destination. See [core](../core/README.md#env-the-secrets-core-reads). |
| [`core/evals/`](../core/evals/) | The question and the two answers of each eval. One file is one eval. See [Human evals](./human-evals.md). |
| [`core/modules/dashboard/`](../core/modules/dashboard/) | `dashboard_base.yaml`: the panels that every dashboard has.<br>`dashboard_for_app.yaml`: the SQL of each panel in the Dashboard view of the RateXp app.<br>`dashboard_for_dynatrace.yaml`: the DQL of each panel in the Dynatrace dashboard and the RateXp Dynatrace app.<br>See [ADR 0001](./adr/0001-one-panel-list-for-every-dashboard.md). |
| [`app/ratexp/config.yaml`](../app/ratexp/config.yaml) | The read source, the rows of the Feedback table and of the downloads (for every dashboard), the query box, the live feed, and the core in the install popup. See [app/ratexp](../app/ratexp/README.md#config-every-key-in-configyaml). |
| `app/ratexp/.env` ([example](../app/ratexp/.env.example)) | The database, the URL and token of each read source, the allowed origins, and the URL of core. See [app/ratexp](../app/ratexp/README.md#env-the-secrets-the-app-reads). |
| [`app/dynatrace/app.config.json`](../app/dynatrace/app.config.json) | The tenant, the id, name and version of the app, and its scopes. See [app/dynatrace](../app/dynatrace/README.md#config-every-key-in-appconfigjson). |
| [`seeder/config.yaml`](../seeder/config.yaml) | The model, the prompts, the eval, and how often the local loop runs. See [seeder](../seeder/README.md#config-every-key-in-configyaml). |
| `seeder/.env` ([example](../seeder/.env.example)) | The keys of the model, the URL of core, and the schedule of the deployed timers. See [seeder](../seeder/README.md#env-the-secrets-the-seeder-reads). |
| [`docs-server/mkdocs.yml`](../docs-server/mkdocs.yml) | The pages, the sidebar and the look of the docs site. See [docs-server](../docs-server/README.md#config-every-key-in-mkdocsyml). |
| `.env` at the repo root | The local stack: the ports `CORE_HOST_PORT` and `APP_HOST_PORT`, `DATABASE_URL` and `RATEXP_PUBLIC_URL`. [`docker-compose.yml`](../docker-compose.yml) has working defaults. |
| `infra/terraform.tfvars` ([example](../infra/terraform.tfvars.example)) | The Azure subscription and the optional extras of your own copy. See [Custom deploy](./custom-deploy.md). |

## Keep in mind: settings, secrets and keys

- **Settings, not secrets:** A `config.yaml` file holds settings only. A `.env` file holds the
  secrets and the values that change for each environment.
- **Required keys:** Each key in a `config.yaml` file is necessary. If a key is missing, the
  component stops at startup with an error. core checks the eval files at startup with the
  same rules.
- **Key descriptions:** The README of each component tells what each key and each environment
  variable does. The table links to each README.
