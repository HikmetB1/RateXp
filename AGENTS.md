# Notes for coding agents

This repo is agent-agnostic: nothing here depends on a specific assistant
(Claude, Copilot, Cursor, Codex, Ollama-backed tools, ...). These notes help any
agent - or human - work in it safely.

## Project shape

- `core/` - public FastAPI service. Hosts the RateXp MCP server (`/mcp`) and
  ingests feedback/transcripts straight into PostgreSQL.
- `app/app-be/` - private FastAPI service. Read-only dashboard API; also serves
  the built dashboard UI.
- `app/app-fe/` - React dashboard (source).
- `infra/` - one Terraform stack that provisions both web apps + PostgreSQL.
- `examples/` - sample `SKILL.md` files (each with its `.mcp.json`).
- `template/` - copy-and-fill `SKILL.md` + `.mcp.json` for a new skill.

## Ground rules

- Keep each service self-contained. `core/` and `app/app-be/` deliberately
  duplicate small helpers (`db.py`, `migrate.py`, `migrations/`) rather than
  share a package, so either can be built and deployed alone.
- Config that should live outside code goes in each service's `config.yaml`.
  Every key is required - a missing key fails loudly at startup.
- Secrets never go in `config.yaml` or git. They come from environment
  variables (local) or Managed Identity (cloud).
- Update tests and docs in the same change as the code.

## Common commands

See [CONTRIBUTING.md](./CONTRIBUTING.md) for how to run, test, and configure
everything.
