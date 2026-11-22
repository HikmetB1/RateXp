# ADR 0004: The plugins install from the RateXp repo

- **Status:** Accepted
- **Scope:** The RateXp plugins for Claude Code and for the Cursor CLI.
- **Replaces:** [ADR 0003](./0003-each-plugin-has-its-own-repo.md).

## Context: two plugin repos for one product

- **Two more repos:** ADR 0003 sent each plugin folder to its own repo with
  `git subtree push`. Thus, RateXp had three repos on GitHub, and each plugin change needed
  a release step.
- **Folder sources:** A marketplace entry can name a folder in a git repo (`git-subdir`).
  Claude Code then downloads only that folder. The Cursor CLI also accepts a folder of the
  repo that holds the marketplace (`./plugins/cursor`).

## Decision: two marketplace files at the root of this repo

- **Claude Code:** `.claude-plugin/marketplace.json` names `plugins/claude-code/` in
  `https://github.com/HikmetB1/RateXp.git` as a `git-subdir` source. Users add this
  marketplace by the web address of the file on GitHub. Thus, Claude Code downloads the
  marketplace file and `plugins/claude-code/`, about 100 KB, not the whole repo.
- **Cursor CLI:** `.cursor-plugin/marketplace.json` names `./plugins/cursor`. Users add the
  marketplace with the address of the repo: `https://github.com/HikmetB1/RateXp`.
- **Each agent reads its own file:** The Cursor CLI reads `.cursor-plugin/marketplace.json`
  before `.claude-plugin/marketplace.json`. Claude Code reads only
  `.claude-plugin/marketplace.json`.
- **No plugin repos:** The plugin folders hold no marketplace file. A push of `main` to
  GitHub publishes a plugin change.

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
