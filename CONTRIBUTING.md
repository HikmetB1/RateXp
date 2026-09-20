# Contributing to RateXp

- [The three services](#the-three-services)
- [Config and env](#config-and-env)
- [Running locally](#running-locally)
- [Deploy to Azure](#deploy-to-azure)
- [Repository layout](#repository-layout)
- [Tests](#tests)
- [TODO](#todo)
- [README rules](#readme-rules)
- [Code rules](#code-rules)
- [Contributor License Agreement](#contributor-license-agreement)

## The three services

The repo stands on three services. Each one builds, tests and deploys on its own, and each has
its own README covering its layout, how to run it and what it reads:

| Service | What it is |
|---------|------------|
| [core](./core/README.md) | Hands out the hook script, takes back the ratings and transcripts it posts, masks anything personal, and writes the result to every destination you switched on. |
| [app](./app/README.md) | The dashboard. Reads the stored feedback back from one source and shows it as it arrives. |
| [seeder](./seeder/README.md) | Optional. On a timer, an agent uses one of the bundled skills and rates it, so a demo dashboard is never empty. |

Both use adapters, switched on in `config.yaml`: core **writes** to every one enabled, app
**reads** from exactly one - today PostgreSQL, so the filter box takes SQL.

## Config and env

Each service carries its own settings in two files beside its code:

| Service  | Settings                                  | Secrets                            |
|----------|-------------------------------------------|------------------------------------|
| core     | [`core/config.yaml`](./core/config.yaml)     | `core/.env` ([example](./core/.env.example))     |
| app      | [`app/config.yaml`](./app/config.yaml)       | `app/.env` ([example](./app/.env.example))       |
| seeder   | [`seeder/config.yaml`](./seeder/config.yaml) | `seeder/.env` ([example](./seeder/.env.example)) |

- `config.yaml` holds the non-secret tunables. **Every key is required** - a missing one fails
  loudly at startup, so the file is the single source of truth.
- `.env` holds the secrets and per-environment wiring; all three are gitignored.
- What each key and variable means is listed in that service's README:
  [core](./core/README.md), [app](./app/README.md), [seeder](./seeder/README.md).

	> Stack wiring that spans services (ports, `DATABASE_URL`, `RATEXP_PUBLIC_URL`) has working
defaults in [`docker-compose.yml`](./docker-compose.yml); to override one, put it in a root
`.env`, which compose reads automatically.

## Running locally

**Prerequisite:** Docker with Docker Compose **v2** (the `docker compose` command, with a
space). The whole stack - PostgreSQL + core + dashboard - comes up with one command:

```bash
git clone <repo-url> ratexp && cd ratexp
docker compose up --build -d
```

| Service | URL                     | What it is                                               |
|---------|-------------------------|----------------------------------------------------------|
| core    | <http://localhost:8000> | serves `/ratexp.sh`, ingests `/feedback` + `/transcript` |
| app     | <http://localhost:8001> | the dashboard                                            |

`docker compose logs -f core` follows one service's logs; `docker compose down -v` stops
everything and wipes the data.

> You can also run just one service on its own - outside compose, the UI with live reload, or
> the demo seeder. Each service's README shows how:
> [core](./core/README.md#running-locally), [app](./app/README.md#running-locally),
> [seeder](./seeder/README.md#running-locally).

## Deploy to Azure

One Terraform stack creates the whole thing on Azure: two web apps (`core` + `app`), a managed
PostgreSQL server, and a container registry to hold the images. The apps sign in to the
database through Microsoft Entra ID, so there is **no database password** to store anywhere.

**Before you start**, install the Azure CLI (and run `az login`), Terraform and Docker.

**1. Create the Azure resources.**

```bash
cd infra
cp terraform.tfvars.example terraform.tfvars   # put your subscription_id in it
terraform init && terraform apply
```

**2. Build the images and push them to the registry.**

```bash
az acr login --name "$(terraform output -raw acr_name)"
docker build -t "$(terraform output -raw core_image)" ../core && docker push "$(terraform output -raw core_image)"
docker build -t "$(terraform output -raw app_image)" -f ../app/Dockerfile ../app && docker push "$(terraform output -raw app_image)"
```

**3. Let the two apps into the database.** Run
[`infra/grant-db-access.sql`](./infra/grant-db-access.sql) once, connected as the database's
Entra admin. It needs the app names and identity ids, which `terraform output` prints - along
with the URLs your services will be reachable on.

**4. Stop each web app, then start it again.** That is what makes Azure pull the image you
just pushed. `az webapp restart` does **not** - it keeps running the old cached one.

**Optional extras**, switched on in `terraform.tfvars`: `enable_redaction` masks personal data
in transcripts, and `enable_seeder` deploys the demo seeder. With the seeder on, build and
push `seeder_image` the same way as step 2.

## Repository layout

```text
.
├── core/                Public ingestion service: serves the hook script, stores feedback
│   ├── ratexp.sh        The hook itself - the source of every shipped copy
│   ├── install.sh       What `curl … | bash -s skill my-skill` runs
│   ├── api/             The HTTP surface: routes, schemas, rate limiting, ATIF building
│   ├── modules/
│   │   ├── redaction/   PII masking: presidio (in-process) or azure (AI Language)
│   │   └── write/       Write destinations + the fan-out + the SQL migrations
│   ├── template/        Blank starting points: skill/ and plugin/
│   ├── examples/        The poem skill packaged both ways, hooks already wired
│   └── tools/           Dev-only, never shipped: sync_hooks.py regenerates the hook copies
├── app/                 Dashboard service: read-only API, and it serves the UI
│   ├── api/             The HTTP surface: routes, schemas, snapshots, the live feed
│   ├── modules/read/    Read sources - the dashboard reads from the one enabled source
│   └── FE/              React dashboard (source)
├── seeder/              Optional demo seeder: an agent uses a skill, then rates it
│   ├── api/             One run end to end, and the two ways one gets started
│   ├── azure_function/  The deployed timer trigger + host.json
│   ├── modules/
│   │   ├── agent/       The model, the skill pool, and the sandboxed run itself
│   │   └── submit/      Messages → ATIF, and the two posts to core
│   └── skills/          The skills the agent picks from (third-party, see ATTRIBUTION.md)
├── infra/               Terraform stack for Azure (two web apps + PostgreSQL)
├── tests/               Whole-app integration tests (run against a live/local stack)
├── assets/              Images the README shows (banner, demo GIF, dashboard shot)
├── docker-compose.yml   Local stack: PostgreSQL + core + app (+ opt-in seed profile)
├── THIRD_PARTY_NOTICES.md  Licenses and citations for projects RateXp builds on
├── CLA.md / LICENSE / CITATION.cff  Contributor agreement, license, how to cite
└── pyproject.toml       Shared ruff config; each service has its own project file
```

`core/`, `app/` and `seeder/` are each self-contained - they deliberately duplicate small
helpers (database connection, config loading) so any one of them can be built and deployed on
its own.

## Tests

**Per-service** tests are fast and mocked - no network or database needed. Each one runs the
same way from its own folder; the command is in that service's README:
[core](./core/README.md#tests), [app](./app/README.md#tests), [seeder](./seeder/README.md#tests).

**Whole-app** tests in `tests/` check the services working together over HTTP - core writes
feedback, the dashboard reads it back. Bring the stack up first:

```bash
docker compose up --build -d
uv run --no-project --with pytest --with httpx pytest tests/
```

| File                | Checks                                                                     |
|---------------------|-----------------------------------------------------------------------------|
| `test_smoke.py`     | Both services answer `/healthz`; core serves `/ratexp.sh` with its URL baked in and accepts a `/feedback` post. |
| `test_end_to_end.py`| A rating (and a consented trajectory) posted to core appears on the dashboard and in its top-skills stats; the last test drives the *shipped* hook script, so the exact bytes a real skill puts on the wire are the ones checked. |
| `test_azure_live.py`| Opt-in smoke test against the deployed Azure web apps (skipped by default). |

If the stack isn't running, these skip with a hint. They default to the compose ports
(`8000`/`8001`); point elsewhere with `RATEXP_CORE_URL` / `RATEXP_APP_URL`. To smoke the
deployed apps instead:

```bash
export RATEXP_AZURE_LIVE=1
export RATEXP_AZURE_CORE_URL=https://<your-core>.azurewebsites.net
export RATEXP_AZURE_APP_URL=https://<your-app>.azurewebsites.net
pytest tests/test_azure_live.py
```

## TODO

- [ ] Expand to more coding agents (e.g. GitHub Copilot).
- [ ] Fix truncated trajectories when the dashboard reads from Dynatrace: a very large `atif`
      exceeds Dynatrace's per-attribute storage cap, so it is truncated on ingest → invalid
      JSON → the read adapter returns an empty stub (`dynatrace_truncated`) → the viewer shows
      nothing (PostgreSQL still shows it in full). Fix by shipping transcripts as **one log
      line per step**, and/or surfacing `dynatrace_truncated` in the UI. Normal-sized
      transcripts are unaffected.
- [ ] Build a Dynatrace dashboard over the fanned-out `ratexp.*` logs, so ratings and
      trajectories can be viewed natively in Dynatrace. Open question: dashboard or a
      Dynatrace App.

## README rules

These are about the README inside a folder. Your reader knows the project but has never
opened this folder. The root [README.md](./README.md) and this file are the two exceptions -
they are read front to back by someone who knows nothing yet, so they may run long.

1. **Write only what the folder cannot show by itself.**
   `ls` lists the files, docstrings explain the functions, `--help` prints the flags.
   Write down what stays hidden: a rule that fails silently, a generated file, an order
   that must not change. Nothing hidden, no README.

2. **Say each fact once.**
   A fact is anything that can quietly go out of date: a path, a command, a flag, a
   default, a version. Keep it in the one file closest to what it describes, and link to
   it from everywhere else. Check the code before writing it down.

3. **Keep every section to a line or two.**
   A folder README answers the same six questions in the same order: what happens here,
   layout, running locally, config and env, tests, deploy. Anything longer than two lines
   is documentation and belongs where that subject already lives.

4. **Fix it in the same commit that breaks it, or delete it.**
   The trigger is "I changed something this README states". So name exact paths and
   commands: a rename you can grep for is the only warning you get. When the folder can
   speak for itself, delete the file.

5. **Describe how things are now, not what changed.**
   The reader never saw the old version, so nothing here has to correct it. No
   "previously", no old versus new. That story belongs in the commit message.

6. **Copy the shape of the README next door.**
   Folders get read side by side, so the same question should carry the same heading in
   each: `core/README.md` puts its settings under `## Config`, one bullet per key, and
   `app/README.md` follows it. A second shape for one job costs the reader a re-read.

## Code rules

Code has two readers who read the same way: a person skimming fast, and an agent holding
a few hundred lines, never the whole project. One pass should be enough for both.

1. **Write the least code that does the job.**
   No layer without a caller, no option nobody passes, no abstraction for a second case
   that does not exist. Two callers are a pattern, one is a guess.

2. **Make the call readable without opening the function.**
   The name has to carry what it returns, what it changes, and what it costs. A long
   name beats a comment explaining a short one.

3. **Name a file for the action it performs, where it performs one.**
   `redact_trajectory.py` and `apply_migrations.py` say what the file does before you
   open it. `utils.py` and `helpers.py` say nothing. Where a file is a thing rather
   than an action, name it that thing: `record_schemas.py`.

4. **Keep each file understandable on its own.**
   Import explicitly and keep the flow on the page. No relying on import order or a side
   effect three folders away. If a second file is required reading, say so once at the top.

5. **Comments say why, not what.**
   The code already says what it does. Comment a choice that looks wrong but is not, a
   constraint from outside the file, an order that must not change.

6. **Delete dead code instead of keeping it.**
   Commented-out blocks, unused helpers, dead flags, shims for callers that are gone.
   Remove them in the commit that kills them. Git remembers, readers assume it matters.

7. **Leave nothing that only makes sense against the old design.**
   Rule 6 for a whole feature. You are done when no name, branch, or comment points at
   what used to be there: no `v2` or `new_` beside the thing it replaced, no old path
   kept alive.

8. **Find the convention before you invent one.**
   The repo has usually answered your question already, so read a sibling before naming a
   file, shaping a module, or reaching for a path. `modules/read/` mirrors `modules/write/`
   file for file because of it. Follow what you find, or change every copy in one commit.

## Contributor License Agreement

Before your contribution can be merged, you agree to the
[Contributor License Agreement](./CLA.md). You accept it automatically by submitting a pull
request; sign your commits with `git commit -s` (adds a `Signed-off-by` line) to confirm. In
short: you keep your own rights, but you grant the owner a license to your contribution -
including the right to relicense it later.



check tests on main if they really make sense
go through readmes 
adapter for arize
pitch deck add to git ignore
pitch deck arize offer annotation from the ui the human feedback I am on the go
add it to every session ened of claude not just skills for claude admins
add to readmes configs boundary values if any