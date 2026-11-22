# ADR 0003: Each plugin has its own repo

- **Status:** Replaced by [ADR 0004](./0004-the-plugins-install-from-the-ratexp-repo.md)
- **Scope:** The RateXp plugins for Claude Code and for the Cursor CLI.

## Context: an install copied the whole repo

- **Marketplace download:** `claude plugin install --marketplace` and
  `agent plugin marketplace add` download the whole repo that holds the marketplace.
- **The old layout:** The marketplace and the plugin were at the root of this repo. Thus, each
  user downloaded and installed all of RateXp: 247 files, about 18 MB. The agent used only 3
  or 4 of these files.
- **The risk:** Users and security reviewers see Terraform, Dockerfiles and a backend in the
  folder of a plugin. That makes them ask what else the plugin does.

## Decision: a folder for each agent, published to its own repo

- **One folder for each agent:** `plugins/claude-code/` and `plugins/cursor/` each hold one
  complete plugin: the manifest, the marketplace, the `/ratexp:rate` skill, the hook script
  and the license.
- **Own repo:** `infra/publish-plugins.sh` sends each folder to its own repo with
  `git subtree push`: `HikmetB1/ratexp-claude-plugin` and `HikmetB1/ratexp-cursor-plugin`.
  Users install from these repos.
- **One place to change:** All changes and tests stay in this repo. Nobody edits the plugin
  repos.
- **Two independent plugins:** A Claude Code install does not install RateXp for the Cursor
  CLI. Each agent has its own install.

## Consequences: what changes for users and for releases

- **Small download:** A user downloads only the plugin of their agent: 6 files for Claude
  Code, 7 for the Cursor CLI.
- **One more release step:** After prod has the new core and `main` is on GitHub, run
  `infra/publish-plugins.sh`. See
  [Deploy a change](../custom-deploy.md#deploy-a-change-dev-first-then-prod).
- **Same version:** Both manifests have the same version. core reads the version from
  `plugins/claude-code/.claude-plugin/plugin.json` and sends it at `/hook-settings`.
- **Cursor users install RateXp in the Cursor CLI too:** The Cursor CLI also reads plugins
  that Claude Code installed, and shows the Claude Code skill as `/rate`. The Claude Code
  plugin has no Cursor part. Thus, in the Cursor CLI, its skill only tells the user to
  install the Cursor plugin.
