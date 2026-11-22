# ADR 0003: The plugins install from the RateXp repo

- **Status:** Accepted
- **Scope:** The RateXp plugins for Claude Code and for the Cursor CLI.

## Context: an install must not copy the whole repo

- **Marketplace download:** An agent downloads the repo that holds a marketplace. A plugin at
  the root of this repo makes each user download all of RateXp: about 260 files, 17 MB. The
  agent uses only a few of these files.
- **The risk:** Users and security reviewers see Terraform, Dockerfiles and a backend in the
  folder of a plugin. That makes them ask what else the plugin does.
- **Repos for each plugin:** A separate repo for each plugin keeps the download small, but
  adds a release step and two more repos to keep in step with this repo.

## Decision: a folder for each agent, two marketplace files at the repo root

- **One folder for each agent:** `plugins/claude-code/` and `plugins/cursor/` each hold one
  complete plugin: the manifest, the `/ratexp:rate` skill, the hook script and the license.
- **Claude Code:** `.claude-plugin/marketplace.json` names `plugins/claude-code/` in
  `https://github.com/HikmetB1/RateXp.git` as a `git-subdir` source. Users add this
  marketplace by the web address of the file on GitHub. Thus, Claude Code downloads only the
  marketplace file and `plugins/claude-code/`: about 120 KB.
- **Cursor CLI:** `.cursor-plugin/marketplace.json` names `./plugins/cursor`. Users add the
  marketplace with the address of the repo, `https://github.com/HikmetB1/RateXp`. The Cursor
  CLI downloads only the files at the repo root and `plugins/cursor/`: about 350 KB.
- **Each agent reads its own file:** The Cursor CLI reads `.cursor-plugin/marketplace.json`
  before `.claude-plugin/marketplace.json`. Claude Code reads only
  `.claude-plugin/marketplace.json`.
- **One place to change:** All changes and tests stay in this repo. The plugin folders hold
  no marketplace file.
- **Two independent plugins:** A Claude Code install does not install RateXp for the Cursor
  CLI. Each agent has its own install.

## Consequences: what changes for users and for releases

- **Long Claude Code command:** The Claude Code install command names the web address of the
  marketplace file. Users copy the command from the README or from the install popup of the
  RateXp app.
- **No release step:** A plugin change reaches users when `main` is on GitHub. Push `main`
  after prod has the new core. See
  [Dev environment](../custom-deploy.md#dev-environment-test-a-change-before-prod).
- **Local tests:** A test loads a plugin folder with `--plugin-dir`. The marketplace files
  name GitHub, so they install only what is on GitHub.
- **Same version:** Both manifests have the same version. core reads the version from
  `plugins/claude-code/.claude-plugin/plugin.json` and sends it at `/hook-settings`.
- **Cursor users install RateXp in the Cursor CLI too:** The Cursor CLI also reads plugins
  that Claude Code installed, and shows the Claude Code skill as `/rate`. The Claude Code
  plugin has no Cursor part. Thus, in the Cursor CLI, its skill only tells the user to
  install the Cursor plugin.
