# seeder

The seeder keeps the demo dashboard from being empty: on a timer, an agent picks one of the
bundled skills, actually does a small task with it, then rates the skill and posts that rating
and its trajectory to core like any real hook would. It is entirely optional and it spends
model credits, so nothing starts it by accident.

## Layout: what lives in this folder

```text
seeder/
├── api/                 seed_once.py is one run end to end; run_continuously.py repeats it
├── azure_function/      the deployed timer trigger + host.json, flattened into the image root
├── modules/
│   ├── agent/           the model, the skill pool, and the sandboxed run itself
│   └── submit/          messages → ATIF, and the two posts to core
├── skills/              the pool a run picks from (third-party, see ATTRIBUTION.md)
├── tests/               the seeder's own tests: mocked, no model calls
├── config.yaml          the settings below; load_config.py reads it
├── requirements.txt     the runtime deps - the Functions image installs from here, not uv.lock
└── Dockerfile           the Azure Functions base image; compose overrides the entrypoint
```

Because `requirements.txt` is the real dependency list, `uv lock` alone will not notice an
edit to it - run `uv lock --refresh`.

## Running locally: start it on your machine

From the repo root, this starts the seeder beside core and the dashboard. It sits behind an
opt-in profile, since every run costs model credits - put the key for the model in
`config.yaml` into `seeder/.env` first:

```bash
cp seeder/.env.example seeder/.env
docker compose --profile seed up --build -d
```

To run the loop on its own instead, without compose - there is no Functions runtime locally:

```bash
uv sync && uv run python -m api.run_continuously
```

## Config: every key in config.yaml

[`config.yaml`](./config.yaml) - every key is required, a missing one fails at startup:

- `schema_version`: ATIF version stamped on every seeded trajectory (matches core's)
- `model` / `temperature` / `max_rounds`: which model runs a skill, how it samples, and how
  many turns it gets before it has to rate
- `core_url`: where the rating and the trajectory are posted
- `eval_name`: the eval the rating answers, named as in core's [`evals/`](../core/evals/) -
  the prompts below ask its question
- `interval_seconds`: gap between runs for the local loop only - the deployed timer takes its
  cadence from `SEED_SCHEDULE` instead
- `critical_ratio` / `oversized_ratio`: share of runs that review harshly, and share bloated
  past core's size limit on purpose so core stores a meta-only stub
- `system_prompt` / `task_prompt` / `critical_prompt`: the agent's own instructions

## Env: the secrets it reads

Secrets and per-environment wiring, in `seeder/.env` ([example](./.env.example)):

- `OPENAI_API_KEY`: needed when `model` starts `openai:`
- `AZURE_OPENAI_ENDPOINT` / `OPENAI_API_VERSION` / `AZURE_OPENAI_API_KEY`: needed when `model`
  starts `azure_openai:`. The key is optional - on Azure it reaches the model passwordlessly
  through its Managed Identity
- `MODEL` / `RATEXP_CORE_URL`: override the two `config.yaml` keys of the same meaning, so a
  deployment can point elsewhere without editing the file
- `SEED_SCHEDULE`: the deployed timer's cadence, NCRONTAB with seconds (`*/30 * * * * *` is
  every 30s). Ignored by the local loop

## Tests: how to run them

```bash
uv sync --extra test && uv run pytest
```

Mocked, so no model is called and no credits are spent - the chat model and core are stubbed.

## Deploy: how it gets to Azure

The seeder is an Azure Function App, off by default: set `enable_seeder = true` in tfvars and
push `seeder_image`. See
[Deploy to Azure](../CONTRIBUTING.md#deploy-to-azure-from-zero-to-live).
