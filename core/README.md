# core

core hands out the hook script, takes back whatever the hook posts, masks anything personal,
and writes the result to every destination switched on - the hook only ever posts to the same
two endpoints and never knows where the data ends up. That is true whether it is rating one
skill or a whole coding-agent session; only what arms it, and how much of the conversation it
covers, differ.

```mermaid
sequenceDiagram
    participant A as Skill author or coding agent user
    participant H as the hook script
    participant C as core
    participant D as Destinations

    Note over A,C: once, while setting up
    A->>C: GET /install.sh, then run it
    C-->>A: the hook, named for what it rates, pointing back at this core
    A->>H: a skill folder, or .claude/ with its hooks pasted into settings.json

    Note over H,D: then every Nth run of that skill, or every Nth turn of the session
    H->>C: POST /feedback (rating, optional comment)
    opt user consented
        H->>C: POST /transcript (the skill's run, or the session so far)
        C->>C: rebuild the conversation, then mask personal data
    end
    C->>D: write to every enabled destination
    C-->>H: 201 stored, or 503 if none accepted
```

## Quick start: install in one command

Pick the command that satisfies your use case, nothing to configure. Needs Claude Code, Bash 3.2+ and curl - run it
from your project root:

```bash
# Pick one

# Use case: A skill Author would like to stay close to the skill users and get their feedback
# A skill  ->  creates .claude/skills/my-skill/ -> Update your SKILL.md in your skill folder as usual
curl -fsSL https://ratexp-core.azurewebsites.net/install.sh | bash -s skill my-skill

# Use case: A coding agent provider or access admin would like to stay close to the coding agent users and get their feedback
# The coding agent itself  ->  creates .claude/ratexp-coding-agent.sh -> then paste the hooks it prints into .claude/settings.json
curl -fsSL https://ratexp-core.azurewebsites.net/install.sh | bash -s session claude
```

That is the whole setup. Ratings land on the
[dashboard](https://ratexp-app.azurewebsites.net/).

### How often it asks: every 2nd run or turn

- **Skill** - every 2nd **run** of that skill, so it never nags.
- **Coding agent** - every 2nd **turn** of the session, and `/ratexp` asks on the spot.

Change `DEFAULT_EVERY` at the top of the hook script the install put in place -
`ratexp-skill.sh` or `ratexp-coding-agent.sh` - to change the default for everyone you
ship it to.

Want to run your own core instead of the hosted one? See
[CONTRIBUTING.md](../CONTRIBUTING.md#deploy-to-azure-from-zero-to-live).

## Layout: what lives in this folder

```text
core/
├── ratexp-skill.sh      the hook a skill ships with - source of the copies
├── ratexp-coding-agent.sh  the hook that rates a whole session; installed, never bundled
├── install.sh           what `curl … | bash -s skill my-skill` runs
├── api/                 routes, record schemas, rate limiting, ATIF trajectory building
├── modules/
│   ├── redaction/       masks PII before storage: the presidio or azure adapter
│   └── write/           the destinations, the fan-out, and the SQL migrations
├── template/            blank starting points: skill/ and session/
├── examples/            the poem skill, hooks already wired
├── tools/sync_hooks.py  regenerates the copies above (dev only, never in the image)
├── tests/               core's own tests: mocked, no network or database
├── config.yaml          the settings below; load_config.py reads it
└── Dockerfile           builds every optional adapter in, so config alone picks what runs
```

## Running locally: start it on your machine

From the repo root, this puts core on <http://localhost:8000>, beside PostgreSQL and the
dashboard:

```bash
docker compose up --build -d
```

Compose mounts this folder, so edits reload in place and each hook is re-read per request.
To run core on its own instead, you install the extras your `config.yaml` switches on
yourself - the Dockerfile installs all of them, `uv sync` installs none, and Presidio
additionally needs the per-language spaCy models the Dockerfile downloads:

```bash
uv sync --extra redaction-presidio --extra dynatrace-otlp
DATABASE_URL=postgresql://ratexp:ratexp@localhost:5432/ratexp uv run uvicorn api.serve_http:app --reload
```

## Config: every key in config.yaml

[`config.yaml`](./config.yaml) - every key is required, a missing one fails at startup:

- `schema_version`: ATIF version stamped on every stored transcript
- `max_body_bytes`: biggest request body core accepts, in bytes - the cap that guards
  `/transcript`. A bigger one is turned away with `413` and nothing is kept, not even a stub,
  so set it higher than `max_transcript_bytes`. The hook never sends more than 4 MiB at once
- `max_transcript_bytes`: largest trajectory stored in full; a bigger one keeps only a
  meta-only stub, so a few huge conversations can't bloat the database
- `rate_limit_per_minute`: per-IP budget; `0` turns the limiter off
- `default_survey_every`: ask on every Nth run, baked into the hook copies
- `redaction`: whether personal data is masked and which adapter does it - `presidio`
  (in-process, free) or `azure` (AI Language, billed per 1,000 records). Both are in the
  image, so switching is one value plus a restart, never a rebuild
- `write_adapters`: the destinations every submission is written to. They are independent -
  one failing is logged and never blocks the others - but the request fails with `503` if
  none of them accepted. Each shapes a record its own way:
  - `app_be_psql`, `custom_psql` - one table row
  - `app_be_dynatrace`, `custom_dynatrace`, `bluebox` - one OTLP log line
  - `phoenix` - one span

## Env: the secrets it reads

Secrets and per-environment wiring, in `core/.env` ([example](./.env.example)):

- `DATABASE_URL` / `RATEXP_DB_AUTH`: the PostgreSQL `app_be_psql` writes to, and how to
  authenticate - `password` locally, `entra` (Managed Identity) on Azure
- `RATEXP_PUBLIC_URL`: the base URL baked into the hooks and `install.sh` core serves,
  so the hooks it hands out post back to the right place
- `RATEXP_REDACTION_PROVIDER`: overrides `redaction.provider` for one deployment
- `DT_TENANT_URL` / `DT_ACCESS_TOKEN`, `CUSTOM_PSQL_DSN`, `CUSTOM_DT_TENANT_URL` /
  `CUSTOM_DT_TOKEN`, `BLUEBOX_OTLP_ENDPOINT` / `BLUEBOX_OTLP_TOKEN`,
  `PHOENIX_COLLECTOR_ENDPOINT` / `PHOENIX_API_KEY` / `PHOENIX_PROJECT_NAME`: one group per
  destination, named (never valued) in `config.yaml`. A destination missing its value is
  skipped with a warning instead of failing

## Tests: how to run them

```bash
uv sync --extra test && uv run pytest
```

Mocked, so no network or database. They also drive the hooks themselves with a fake curl, and
`test_templates.py` fails if any copy under `template/` or `examples/` has drifted.

## Deploy: how it gets to Azure

core is one of the two web apps in the Terraform stack - see
[Deploy to Azure](../CONTRIBUTING.md#deploy-to-azure-from-zero-to-live).

## Hook copies: edit the original, not the copies

Each hook in this folder is an original. Each has two blanks in it: where to post, and how
often to ask. Those blanks get filled in two different ways:

- `GET /ratexp-skill.sh` and `/ratexp-coding-agent.sh` fill them in while serving the file,
  so every download points back at the core that served it.
- `tools/sync_hooks.py` fills them in and writes two ready-made copies under `template/` and
  `examples/`, both pointing at the hosted core.

The copies are named for what they rate, because the file name is what picks the hook's
behaviour: `ratexp-skill.sh` rates the skill's own runs, and `ratexp-coding-agent.sh` rates
the session it is running in.

Those two copies are generated, so editing one is pointless - the next sync overwrites it.
Edit the original in this folder instead, then regenerate:

```bash
python3 tools/sync_hooks.py          # rewrite the two copies
python3 tools/sync_hooks.py --check  # only say which are out of date (the tests run this)
```

Adding a new template or example? Add its path to the list at the top of
[`tools/sync_hooks.py`](./tools/sync_hooks.py) too - otherwise its copy ships with the blanks
still in it, and posts nowhere.
