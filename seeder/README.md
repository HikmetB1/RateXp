# seeder

The seeder adds ratings to the demo dashboard, so that the demo dashboard is never empty. On
each tick, the seeder makes two separate runs:

- **Skill run:** An agent selects one of the bundled skills, does a small task with the skill,
  and rates the skill.
- **Session run:** An agent does a plain coding task and rates the whole session.
- **Posts:** Each run sends its rating and its trajectory to core, as a real hook script does.
  When the run has a rating, the trajectory post also carries the score and the comment.
- **Optional:** The seeder is optional. Each run costs model credits. Thus, the seeder never
  starts by accident.

## Layout: what this folder holds

```text
seeder/
├── api/                 seed_once.py does one skill run or session run from start to end; run_continuously.py repeats both runs
├── azure_function/      the two deployed timer triggers and host.json, copied flat into the image root
├── modules/
│   ├── agent/           the model, the skill pool, and the sandboxed skill runs and session runs
│   └── submit/          messages → ATIF, and the two posts to core
├── skills/              the pool that a run selects from (third-party, see ATTRIBUTION.md)
├── tests/               the tests of the seeder: mocked, with no model calls
├── config.yaml          the settings below; load_config.py reads config.yaml
├── requirements.txt     the runtime dependencies: the Functions image installs from requirements.txt, not from uv.lock
└── Dockerfile           the Azure Functions base image; compose overrides the entrypoint
```

`requirements.txt` is the real dependency list, but `uv lock` does not see a change to
`requirements.txt`. After you change `requirements.txt`, run `uv lock --refresh`.

## Run locally: start the seeder on your machine

The seeder runs only with the opt-in `seed` profile, because each run costs model credits. To
start the seeder with core and the dashboard, do these steps from the repo root:

1. Copy the example env file:

   ```bash
   cp seeder/.env.example seeder/.env
   ```

2. In `seeder/.env`, write the key for the model that `config.yaml` names.
3. Start the stack with the `seed` profile:

   ```bash
   docker compose --profile seed up --build -d
   ```

To run the seeder loop without compose, run this command. The local loop does not use the Azure
Functions runtime.

```bash
uv sync && uv run python -m api.run_continuously
```

## Config: every key in config.yaml

Each key in [`config.yaml`](./config.yaml) is necessary. If a key is missing, the seeder stops
at startup with an error.

- `schema_version`: The ATIF version on each seeded trajectory. The value is the same as in
  core.
- `model` / `temperature` / `max_rounds`: The model that runs a skill or a session, how the
  model samples, and how many turns the model gets before the model must rate.
- `core_url`: The core that the seeder sends the rating and the trajectory to.
- `eval_name`: The eval that the rating answers, with the name of a file in the
  [`evals/`](../core/evals/) of core. The prompts below ask the question of the `eval_name` eval. The
  rating and the trajectory both carry the eval name. Thus, the Dynatrace dashboard can filter
  transcripts by eval.
- `interval_seconds`: The time between two rounds (one skill run, then one session run), for
  the local loop only. The deployed timers use `SEED_SCHEDULE`.
- `critical_ratio` / `oversized_ratio`: The share of runs that give a harsh review, and the
  share of runs that the seeder makes too large on purpose. core stores an oversized run as a
  stub with only the metadata.
- `system_prompt` / `task_prompt`: The instructions of the agent for a skill run.
- `session_system_prompt` / `session_task_prompt` / `session_tasks`: The instructions of the
  agent for a session run, and the coding tasks that a session run selects from at random.
  The tasks aim at every value of `business_case`, `language` and `task_type` in
  `labeling.groups` of [core's config.yaml](../core/config.yaml), "other" too.
- `comment_focuses`: The aspects that the comment of a run aims at. Each skill run and each
  session run selects one aspect at random. The aspects aim at every value of `feedback_theme`
  in `labeling.groups` of [core's config.yaml](../core/config.yaml). The honest score selects
  the side: praise for a good score, a complaint for a bad score.
- `critical_prompt`: The instructions for a harsh reviewer. The seeder adds
  `critical_prompt` to the `critical_ratio` share of the skill runs and of the session runs.

## Env: the secrets the seeder reads

`seeder/.env` holds the secrets and the settings that change for each environment
([example](./.env.example)):

- `OPENAI_API_KEY`: Necessary when `model` starts with `openai:`.
- `AZURE_OPENAI_ENDPOINT` / `OPENAI_API_VERSION` / `AZURE_OPENAI_API_KEY`: Necessary when
  `model` starts with `azure_openai:`. The key is optional: on Azure, the seeder connects to
  the model without a password, through the Managed Identity of the seeder.
- `MODEL` / `RATEXP_CORE_URL`: Override the two `config.yaml` keys with the same meaning. Thus,
  a deployment can use a different model or core, and you do not edit `config.yaml`.
- `SEED_SCHEDULE`: The schedule of the deployed timers.
  - **Timers:** The skill timer and the session timer use the same schedule.
  - **Format:** NCRONTAB with seconds (`0 * * * * *` is one time each minute).
  - **Local loop:** The local loop ignores `SEED_SCHEDULE`.

## Tests: how to run them

```bash
uv sync --extra test && uv run pytest
```

- **Mocked:** The tests call no model and spend no credits. The tests stub the chat model and
  core.

## Deploy: how the seeder gets to Azure

The seeder is an Azure Function App, and is off by default. To deploy the seeder, set
`enable_seeder = true` in `terraform.tfvars` and push `seeder_image`. See
[Deploy to Azure](../docs/custom-deploy.md#deploy-to-azure-from-zero-to-live).
