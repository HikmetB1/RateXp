# core

core hands out the hook script, takes back whatever the hook posts, masks anything personal,
and writes the result to every destination switched on - `ratexp.sh` only ever posts to the
same two endpoints and never knows where the data ends up.

```mermaid
sequenceDiagram
    participant A as Skill author
    participant H as ratexp.sh
    participant C as core
    participant D as Destinations

    Note over A,C: once, while setting up a skill
    A->>C: GET /install.sh, then run it
    C-->>A: SKILL.md + ratexp.sh, named and pointing back at this core
    A->>H: written into the skill folder

    Note over H,D: then on every Nth run of that skill
    H->>C: POST /feedback (rating, optional comment)
    opt user consented
        H->>C: POST /transcript
        C->>C: rebuild the conversation, then mask personal data
    end
    C->>D: write to every enabled destination
    C-->>H: 201 stored, or 503 if none accepted
```

## Quick start

One command, two files, nothing to configure. Needs Claude Code, Bash 3.2+ and curl - run it
from your project root:

```bash
# Pick one - you only need one of these.

# A plain skill  ->  creates .claude/skills/my-skill/
curl -fsSL https://ratexp-core.azurewebsites.net/install.sh | bash -s skill my-skill

# The same, as a plugin  ->  creates my-plugin/ with the skill nested inside
curl -fsSL https://ratexp-core.azurewebsites.net/install.sh | bash -s plugin my-plugin

# Then go update your skill  ->  write it in SKILL.md, leave the frontmatter alone
```

That is the whole setup. Ratings land on the
[dashboard](https://ratexp-app.azurewebsites.net/).

*Asks every 2nd run by default - change `DEFAULT_EVERY` at the top of `ratexp.sh` to ask more
or less often.*

Want to run your own core instead of the hosted one? See
[CONTRIBUTING.md](../CONTRIBUTING.md#deploy-to-azure).

## Layout

```text
core/
├── ratexp.sh            the hook itself - the source of every copy below
├── install.sh           what `curl … | bash -s skill my-skill` runs
├── api/                 routes, record schemas, rate limiting, ATIF trajectory building
├── modules/
│   ├── redaction/       masks PII before storage: the presidio or azure adapter
│   └── write/           the destinations, the fan-out, and the SQL migrations
├── template/            blank starting points: skill/ and plugin/
├── examples/            the poem skill packaged both ways, hooks already wired
├── tools/sync_hooks.py  regenerates the copies above (dev only, never in the image)
├── tests/               core's own tests: mocked, no network or database
├── config.yaml          the settings below; load_config.py reads it
└── Dockerfile           builds every optional adapter in, so config alone picks what runs
```

## Running locally

From the repo root, this puts core on <http://localhost:8000>, beside PostgreSQL and the
dashboard:

```bash
docker compose up --build -d
```

Compose mounts this folder, so edits reload in place and `ratexp.sh` is re-read per request.
To run core on its own instead, you install the extras your `config.yaml` switches on
yourself - the Dockerfile installs all of them, `uv sync` installs none, and Presidio
additionally needs the per-language spaCy models the Dockerfile downloads:

```bash
uv sync --extra redaction-presidio --extra dynatrace-otlp
DATABASE_URL=postgresql://ratexp:ratexp@localhost:5432/ratexp uv run uvicorn api.serve_http:app --reload
```

## Config

[`config.yaml`](./config.yaml) - every key is required, a missing one fails at startup:

- `schema_version`: ATIF version stamped on every stored transcript
- `max_body_bytes`: largest request body accepted, in bytes (this is what guards `/transcript`)
- `max_transcript_bytes`: largest trajectory stored in full; a bigger one keeps only a
  meta-only stub, so a few huge conversations can't bloat the database
- `rate_limit_per_minute`: per-IP budget; `0` turns the limiter off
- `default_survey_every`: ask on every Nth run, baked into the hook copies
- `redaction`: whether personal data is masked and which adapter does it - `presidio`
  (in-process, free) or `azure` (AI Language, billed per 1,000 records). Both are in the
  image, so switching is one value plus a restart, never a rebuild
- `write_adapters`: the destinations every submission is written to. They are independent -
  one failing is logged and never blocks the others - but the request fails with `503` if
  none of them accepted

## Env

Secrets and per-environment wiring, in `core/.env` ([example](./.env.example)):

- `DATABASE_URL` / `RATEXP_DB_AUTH`: the PostgreSQL `app_be_psql` writes to, and how to
  authenticate - `password` locally, `entra` (Managed Identity) on Azure
- `RATEXP_PUBLIC_URL`: the base URL baked into the `ratexp.sh` and `install.sh` core serves,
  so the hooks it hands out post back to the right place
- `RATEXP_REDACTION_PROVIDER`: overrides `redaction.provider` for one deployment
- `DT_TENANT_URL` / `DT_ACCESS_TOKEN`, `CUSTOM_PSQL_DSN`, `CUSTOM_DT_TENANT_URL` /
  `CUSTOM_DT_TOKEN`, `BLUEBOX_OTLP_ENDPOINT` / `BLUEBOX_OTLP_TOKEN`: one group per
  destination, named (never valued) in `config.yaml`. A destination missing its value is
  skipped with a warning instead of failing

## Tests

```bash
uv sync --extra test && uv run pytest
```

Mocked, so no network or database. They also drive `ratexp.sh` itself with a fake curl, and
`test_templates.py` fails if any copy under `template/` or `examples/` has drifted.

## Deploy

core is one of the two web apps in the Terraform stack - see
[Deploy to Azure](../CONTRIBUTING.md#deploy-to-azure).

## Hook copies

`ratexp.sh` in this folder is the original. It has two blanks in it: where to post, and how
often to ask. Those blanks get filled in two different ways:

- `GET /ratexp.sh` fills them in while serving the file, so every download points back at the
  core that served it.
- `tools/sync_hooks.py` fills them in and writes four ready-made copies under `template/` and
  `examples/`, all pointing at the hosted core.

Those four copies are generated, so editing one is pointless - the next sync overwrites it.
Edit `ratexp.sh` instead, then regenerate:

```bash
python3 tools/sync_hooks.py          # rewrite the four copies
python3 tools/sync_hooks.py --check  # only say which are out of date (the tests run this)
```

Adding a new template or example? Add its path to the list at the top of
[`tools/sync_hooks.py`](./tools/sync_hooks.py) too - otherwise its copy ships with the blanks
still in it, and posts nowhere.
