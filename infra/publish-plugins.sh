#!/usr/bin/env bash
# Publish each RateXp plugin to its own repo. Users add these repos as marketplaces, so
# they download only the plugin of their agent, not this whole repo.
#
#   infra/publish-plugins.sh
#
# Run it from a clone of this repo, after prod has the new core and main is pushed to
# GitHub (docs/custom-deploy.md, "Deploy a change: dev first, then prod"). It sends the
# committed history of plugins/<agent>/ to the main branch of that plugin's repo with
# git subtree push. Change the plugins only in plugins/, never in the plugin repos: a
# commit made there would make the next push fail.
set -euo pipefail

OWNER=HikmetB1

cd "$(git rev-parse --show-toplevel)"
for agent in claude-code cursor; do
  case $agent in
    claude-code) repo=ratexp-claude-plugin ;;
    cursor) repo=ratexp-cursor-plugin ;;
  esac
  echo "plugins/$agent -> github.com/$OWNER/$repo"
  git subtree push --prefix="plugins/$agent" "https://github.com/$OWNER/$repo.git" main
done
