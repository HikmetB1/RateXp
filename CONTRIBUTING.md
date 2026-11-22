# Contributing to RateXp

- [Components](#components-what-each-component-does)
- [Read the feedback](#read-the-feedback-where-each-adapter-shows-ratings)
- [Config and env](#config-and-env-where-settings-live)
- [Run locally](#run-locally-the-whole-stack-at-once)
- [Custom deploy](#custom-deploy-run-your-own-ratexp)
- [Dev environment](#dev-environment-test-a-change-before-prod)
- [Repository layout](#repository-layout-what-each-folder-holds)
- [Tests](#tests-per-component-and-whole-app)
- [Documentation rules](#documentation-rules-how-docs-should-read)
- [Code rules](#code-rules-how-code-should-read)
- [Open work](#open-work-what-is-not-built-yet)
- [Contributor License Agreement](#contributor-license-agreement-what-you-agree-to)

## Components: what each component does

The repo has these components:

- **Separate:** Each component builds, tests and deploys separately.
- **README:** Each component has its own README, with the layout of the component, how to run
  the component and what the component reads.

| Component | What the component is |
|---------|------------|
| [core](./core/README.md) | <ul><li>**Hook scripts:** Holds `ratexp-claude.sh` (Claude Code) and `ratexp-cursor.sh` (Cursor CLI), which the RateXp plugin runs.</li><li>**Plugin settings:** Sends the evals, the default eval, the number of turns and the newest plugin version to the plugin at `/hook-settings`.</li><li>**Ratings and transcripts:** Receives the ratings and the transcripts that the hook scripts send.</li><li>**Redaction and labels:** Masks the personal data and labels each conversation.</li><li>**Destinations:** Writes the result to each destination that is on.</li><li>**Dynatrace dashboard:** `modules/dashboard/publish_to_dynatrace.py` publishes the Dynatrace dashboard.</li><li>**Retention Function:** `core/Dockerfile.retention` builds the retention Function from the same folder. The retention Function deletes old ratings one time each hour.</li></ul> |
| [app/ratexp](./app/ratexp/README.md) | <ul><li>**RateXp app:** The dashboard web app.</li><li>**Data:** Reads the stored feedback from one source, and shows the feedback when the feedback arrives.</li><li>**Dashboard view:** Panels and filters.</li><li>**Query & table view:** The query box.</li></ul> |
| [app/dynatrace](./app/dynatrace/README.md) | <ul><li>**RateXp Dynatrace app:** The same Dashboard view, as an app inside Dynatrace.</li><li>**Data:** Reads the logs that core wrote to Dynatrace.</li><li>**Not the Dynatrace dashboard:** core publishes the Dynatrace dashboard.</li><li>**Optional:** RateXp works without the RateXp Dynatrace app.</li></ul> |
| [seeder](./seeder/README.md) | <ul><li>**Demo ratings:** On a timer, an agent uses one of the bundled skills and rates the skill.</li><li>**Result:** A demo dashboard is never empty.</li><li>**Optional:** RateXp works without the seeder.</li></ul> |
| [docs-server](./docs-server/README.md) | <ul><li>**Docs site:** Builds the markdown of the repo into the pages that core serves at `/guide/`.</li><li>**Deploy:** The core image contains the docs site.</li></ul> |

## Read the feedback: where each adapter shows ratings

See [docs/read-the-feedback.md](./docs/read-the-feedback.md).

## Config and env: where settings live

- **Settings and secrets:** See [docs/config-and-env.md](./docs/config-and-env.md).
- **Secrets out of git:** Git ignores each `.env` file and each `*.tfvars` file. To start one of
  these files, copy the `.env.example` or `terraform.tfvars.example` file next to it.
- **Files that only your machine ignores:** Put these files in `.local.gitignore`, not in the
  shared `.gitignore`. Examples: agent files such as `CLAUDE.md` and `AGENTS.md`, `.claude/`,
  screen recordings and scratch work.
- **Switch on `.local.gitignore`:** Git reads `.local.gitignore` only after you set the repo to
  use the file. After you clone the repo, run this command:

  ```bash
  git config --local core.excludesFile .local.gitignore
  ```

- **Stays on your machine:** The setting is in `.git/config`, and git ignores
  `.local.gitignore`. Thus, the setting and `.local.gitignore` stay on your machine.

## Run locally: the whole stack at once

- **Prerequisite:** Docker with Docker Compose **v2** (the `docker compose` command, with a
  space).
- **Start:** To start the whole stack (PostgreSQL, core and the dashboard), run these commands:

  ```bash
  git clone <repo-url> ratexp && cd ratexp
  docker compose up --build -d
  ```

- **URLs:** What each component does, and where:
  - **core:** <http://localhost:8000>. Serves `/hook-settings` and the docs site at `/guide/`.
    Receives `/feedback` and `/transcript`.
  - **app/ratexp:** <http://localhost:8001>. Serves the dashboard.
- **Logs:** `docker compose logs -f core` shows the live logs of one component (here: core).
- **Stop:** `docker compose down -v` stops the whole stack and deletes the data.
- **One component:** To run one component without the stack, see the README of that component:
  [core](./core/README.md#run-locally-start-core-on-your-machine),
  [app/ratexp](./app/ratexp/README.md#run-locally-start-the-app-on-your-machine),
  [seeder](./seeder/README.md#run-locally-start-the-seeder-on-your-machine).

## Custom deploy: run your own RateXp

See [docs/custom-deploy.md](./docs/custom-deploy.md).

## Dev environment: test a change before prod

See [Dev environment](./docs/custom-deploy.md#dev-environment-test-a-change-before-prod)
in docs/custom-deploy.md.

## Repository layout: what each folder holds

```text
.
├── .claude-plugin/             The RateXp plugin for Claude Code: the manifest with the hooks, and the marketplace
├── .cursor-plugin/             The RateXp plugin for Cursor: the manifest, the hooks and the marketplace
├── core/                       Public ingestion service: serves the hook scripts, stores the feedback
│   ├── ratexp-claude.sh        The Claude Code hook script: rates the session and each skill run in the session
│   ├── ratexp-cursor.sh        The Cursor CLI hook script: does the same as ratexp-claude.sh
│   ├── evals/                  The surveys that users answer: one file for each eval, over a shared base
│   ├── api/                    The HTTP surface: routes, schemas, rate limits, the ATIF builder
│   ├── retention_function/     The retention Function: deletes old ratings one time each hour
│   └── modules/
│       ├── dashboard/          The dashboard definitions: one base, one file for each platform (RateXp app, Dynatrace), the publish command
│       ├── labeling/           Labels each conversation (business case, language, task type) with a low-cost model
│       ├── redaction/          PII masks: presidio (in-process) or azure (AI Language)
│       └── write/              The write destinations, the fan-out and the SQL migrations
├── app/                        The two apps that show the feedback
│   ├── ratexp/                 The RateXp web app: a read-only API that also serves the UI
│   │   ├── api/                The HTTP surface: routes, schemas, snapshots, the live feed
│   │   ├── modules/read/       The read sources: the dashboard reads from the one enabled source
│   │   └── FE/                 The React dashboard (source)
│   └── dynatrace/              The RateXp Dynatrace app: the Dashboard view inside Dynatrace (React + Strato), built with dt-app
├── seeder/                     Optional demo seeder: an agent uses a skill, then rates the skill
│   ├── api/                    One run from start to end, and the two ways to start a run
│   ├── azure_function/         The two deployed timer triggers (skill run, session run) and host.json
│   ├── modules/
│   │   ├── agent/              The model, the skill pool, and the sandboxed run
│   │   └── submit/             Messages → ATIF, and the two posts to core
│   └── skills/                 The skills that the agent selects from (third-party, see ATTRIBUTION.md)
├── docs/                       Guides that span the components (human evals, read the feedback, config and env,
│                               custom deploy), and the decision records in adr/
├── docs-server/                Builds the markdown of the repo into the docs site that core serves at /guide/
├── infra/                      Terraform stack for Azure: two web apps, the retention Function, PostgreSQL, a container registry and the optional extras
├── tests/                      Whole-app integration tests (run against a live stack or a local stack)
├── .github/                    CI checks on each push and pull request, and the issue templates
├── assets/                     Images that the README shows (banner, demo GIFs, dashboard screenshot)
├── docker-compose.yml          Local stack: PostgreSQL, core and app/ratexp (and the opt-in seed and retention profiles)
├── THIRD_PARTY_NOTICES.md      Licenses and citations for the projects that RateXp builds on
├── CLA.md / LICENSE / TERMS.md / CITATION.cff  Contributor agreement, license, terms of the hosted service, how to cite
└── pyproject.toml              Shared ruff config; each component has its own project file
```

For why some files are copied, and why two images read files from outside their folder, see
[ADR 0002](./docs/adr/0002-each-component-builds-on-its-own.md).

## Tests: per-component and whole-app

The tests have two layers: the per-component tests, which you run while you work, and the
whole-app tests, which you run before you push. Two whole-app test files also run against
deployed systems: one against a deployed stack, and one with the real agents on production.

- **Per-component tests:**
  - **Fast and mocked:** The per-component tests use no network and no database.
  - **Command:** Each component runs its tests from its own folder, with the command in its
    README: [core](./core/README.md#tests-how-to-run-them),
    [app/ratexp](./app/ratexp/README.md#tests-how-to-run-them),
    [app/dynatrace](./app/dynatrace/README.md#tests-how-to-run-them),
    [seeder](./seeder/README.md#tests-how-to-run-them),
    [docs-server](./docs-server/README.md#tests-how-to-run-them).
- **Whole-app tests:** core and the RateXp app run for real and talk over HTTP: core stores a
  rating, and the dashboard reads the rating back.
  - **Run:** First start the stack. Then run `tests/`:

    ```bash
    docker compose up --build -d
    uv run --no-project --with-requirements tests/requirements.txt pytest tests/
    ```

  - **What each file checks:**
    - **`test_smoke.py`:** core and the RateXp app answer `/healthz`. core sends the plugin
      its evals at `/hook-settings`, accepts a `/feedback` post, and serves the docs site at
      `/guide/` next to Swagger at `/docs`.
    - **`test_end_to_end.py`:** A rating and a consented trajectory that core receives come
      back out on the dashboard. The last tests run the real `ratexp-claude.sh` to rate a
      skill, as the plugin runs the hook script. Thus, the tests check the bytes that a real
      install sends.
    - **`test_azure_live.py`:** Read-only checks against a deployed stack. pytest skips
      `test_azure_live.py` unless you opt in (see below).
    - **`test_agents_production.py`:** The real `claude` and `cursor-agent` CLIs in a scratch
      project, on production, each with the RateXp plugin loaded for the session: the hooks,
      the `/ratexp:rate` question, and a rating and its trajectory on the dashboard. pytest
      skips `test_agents_production.py` unless you opt in (see below).
  - **Stack URLs:** The tests read `RATEXP_CORE_URL` and `RATEXP_APP_URL`. The defaults are the
    compose ports `8000` and `8001`. Thus, the stack does not have to be local.
  - **No stack:** If core or the RateXp app does not answer, the tests skip with a hint. The
    tests do not fail.

- **Against a deployed stack:**
  - **Safe file:** Only `test_azure_live.py` is safe for a live environment, because
    `test_azure_live.py` only reads.
  - **Test data:** `test_smoke.py` and `test_end_to_end.py` store rows and leave test data.
  - **Run:** pytest skips `test_azure_live.py` until you set these three variables:

    ```bash
    export RATEXP_AZURE_LIVE=1
    export RATEXP_AZURE_CORE_URL=https://<your-core>.azurewebsites.net
    export RATEXP_AZURE_APP_URL=https://<your-app>.azurewebsites.net
    uv run --no-project --with-requirements tests/requirements.txt pytest tests/test_azure_live.py
    ```

- **With the real agents, on production:**
  - **When:** Run `test_agents_production.py` after you deploy a change to
    `core/ratexp-*.sh` or to the plugin files (`.claude-plugin/`, `.cursor-plugin/`).
  - **No local stack:** The test loads the plugin from the repo, sends to the core of
    production and reads the RateXp app of production (for dev, see **Dev**). Thus, the test
    needs no local stack.
  - **Cursor hooks file:** The plugin adds a stop hook that does nothing to
    `~/.cursor/hooks.json` when that file has none. The test puts the file back as it was.
  - **Needs:** A logged-in `claude` and `cursor-agent`, and a few cents of model use.
  - **Scripted part:** The test scripts only the click on the survey.
  - **Test data:** Each run leaves its ratings in the environment that the test runs on, with
    short, masked test conversations. Each test rating has the comment
    `ratexp-live-test <time>`.
  - **Run:**

    ```bash
    RATEXP_PROD_AGENTS=1 uv run --no-project --with-requirements tests/requirements.txt pytest tests/test_agents_production.py -v
    ```

  - **Dev:** Run the test on dev (`ratexp-dev-core` and `ratexp-dev-app`) before you copy the
    images to prod. Then run the test on production again. To run the test on dev, run this
    command:

    ```bash
    RATEXP_PROD_AGENTS=1 RATEXP_AGENTS_ENVIRONMENT=dev uv run --no-project --with-requirements tests/requirements.txt pytest tests/test_agents_production.py -v
    ```

## Documentation rules: how docs should read

- **Where:** The rules apply to each doc in the repo, most of all to the README of a folder.
- **Exception:** The root [README.md](./README.md) and CONTRIBUTING.md introduce the whole
  project, so rule 1 does not apply to README.md and CONTRIBUTING.md.

1. **Write only what the folder cannot show.**
   `ls` lists the files, docstrings explain the functions, and `--help` shows the flags.
   Write down what stays hidden: a rule that fails silently, a generated file, an order that
   must not change. If nothing is hidden, do not write a README.

2. **Say each fact once.**
   A fact is anything that can go out of date without a warning: a path, a command, a flag, a
   default, a version. Keep the fact in the one file closest to what the fact describes, and
   link to that file from all other places. Check the code before you write the fact down.

3. **Fix the doc in the commit that breaks the doc, or delete the doc.**
   - **When:** You change something that a README states. Fix the README in the same commit.
   - **Exact names:** Write exact paths and commands in a README. After a rename, a search
     (`grep`) for the old name then finds the README. Nothing else warns you.
   - **No README needed:** If the folder explains itself, delete the README.

4. **Describe how things are now, not what changed.**
   The reader never saw the old version, so the doc does not have to correct the old version.
   Do not write "previously", and do not compare old with new. That story belongs in the
   commit message.

5. **Copy the shape of the doc next door.**
   - **Before you write:** Open a doc of the same kind next to the doc that you write: another
     component README, another guide in `docs/`, or another ADR in `docs/adr/`.
   - **Copy its shape:** Use the same sections, in the same order, with the same headings.
     Leave out a section that does not apply.
   - **Example:** The component READMEs put their settings under
     `## Config: every key in config.yaml`, with one bullet for each key.
   - **Why:** Readers compare docs side by side. A different shape for the same section makes
     the reader read again.

6. **Put the answer in the heading.**
   `## Tests: how to run them` tells the reader whether to stop or to read on. `## Tests`
   makes the reader guess. Write the title, a colon and three or four words, never a sentence.

7. **Name what you mean.**
   Each sentence must stand on its own: "the RateXp app and the RateXp Dynatrace app", not
   "the two apps"; "Total ratings and Percent good", not "totals". State the general rule, put the
   current cases in brackets, and put the exceptions separately.

## Code rules: how code should read

Code has two readers, and both readers read the same way. One reader is a person who reads
fast. The other reader is an agent that holds a few hundred lines, never the whole project. One
pass must be enough for both readers.

1. **Write the least code that does the job.**
   No layer without a caller, no option that nobody passes, no abstraction for a second case
   that does not exist. Two callers are a pattern. One caller is a guess.

2. **Make the call clear without opening the function.**
   The name must tell what the function returns, what the function changes and what the
   function costs. A long name is better than a comment that explains a short name.

3. **Name a file for the action that the file does, where the file does one action.**
   `redact_trajectory.py` and `apply_migrations.py` tell what the file does before you open
   the file. `utils.py` and `helpers.py` tell nothing. When a file is a thing and not an
   action, give the file the name of that thing: `record_schemas.py`.

4. **Keep each file clear on its own.**
   Import explicitly and keep the flow on the page. Do not depend on the import order, or on
   a side effect three folders away. If the reader must read a second file, say so one time at
   the top.

5. **Comments tell why, not what.**
   The code already tells what the code does. Write a comment for a choice that looks wrong
   but is correct, a constraint from outside the file, or an order that must not change.

6. **Delete dead code. Do not keep dead code.**
   Dead code is commented-out blocks, unused helpers, dead flags, and shims for callers that
   are gone. Remove the dead code in the commit that makes the code dead. Git remembers the
   code, and readers think that the code is important.

7. **Leave nothing that makes sense only with the old design.**
   Rule 6 for a full feature. You are done when no name, branch or comment points to the old
   design. For example: no `v2` or `new_` next to the thing that the new code replaced, and no
   old path that stays alive.

8. **Find the convention before you make a new one.**
   The repo usually has the answer already. Thus, read a sibling before you name a file, shape
   a module or select a path. `modules/read/` mirrors `modules/write/`, adapter for adapter,
   because of rule 8. Only Bluebox, which is write-only, has no read adapter. Follow the
   convention that you find, or change each copy in one commit.

## Open work: what is not built yet

- **Retention for Dynatrace:** The hourly delete (`retention` in `core/config.yaml`) covers only
  PostgreSQL and Phoenix. To add Dynatrace, do these steps:
  1. Give `app_be_dynatrace` and `custom_dynatrace` a `retention` switch.
  2. Write a `delete_old_ratings` for the Dynatrace write adapters. Use the Grail
     [record deletion API](https://docs.dynatrace.com/docs/platform/grail/organize-data/record-deletion-in-grail)
     on the apps host (`DT_QUERY_URL`).
  3. Give the Dynatrace token the `storage:records:delete`, `storage:logs:read` and
     `storage:buckets:read` permissions.
  - **Grail limits:** The record deletion API has these limits:
    - **Age:** The data must be at least 4 hours old.
    - **Size:** One request deletes at most one day of data.
    - **One at a time:** Only one deletion runs at a time.

## Contributor License Agreement: what you agree to

- **Agreement:** Before we can merge your contribution, you agree to the
  [Contributor License Agreement](./CLA.md).
- **Ideas:** Send your idea by email (see [Contact](./README.md#contact-how-to-reach-me)). Then
  we agree how you can contribute.
- **Sign-off:** Sign your commits with `git commit -s`. The `-s` flag adds a `Signed-off-by`
  line.
- **Summary:** You keep your own rights. But you give the owner a license to your
  contribution, with the right to relicense the contribution later.
