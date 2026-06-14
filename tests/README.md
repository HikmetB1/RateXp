# Whole-app tests

The per-service suites (`core/tests/`, `app/app-be/tests/`,
`functions/skills-consumer/tests/`) test each service in isolation with
everything mocked. **This folder is different:** it talks to *running* services
over HTTP and checks they work *together* - core writes feedback, the dashboard
reads it back from the same database.

## What's here

| File | Checks |
|------|--------|
| `test_smoke.py` | Both services answer `/healthz`; core serves the survey snippet. |
| `test_end_to_end.py` | Feedback posted to core appears on the dashboard and in its top-skills stats, and a posted trajectory reads back through the dashboard. |
| `test_azure_live.py` | Opt-in smoke test against the deployed Azure web apps (skipped by default). |

## Run against the local stack

The default targets are the docker-compose ports (`8000` core, `8001`
dashboard). Start the stack, then run the tests:

```bash
docker compose up --build -d        # start core + dashboard + PostgreSQL
pip install -r tests/requirements.txt
pytest tests/                       # local tests run; Azure tests skip
```

If the stack isn't up, the tests **skip** with a hint rather than fail.

Point at different URLs with `RATEXP_CORE_URL` / `RATEXP_APP_URL`.

## Run the live Azure smoke test (opt-in)

Only runs when you give it a deployed environment:

```bash
export RATEXP_AZURE_LIVE=1
export RATEXP_AZURE_CORE_URL=https://ratexp-dev-core.azurewebsites.net
export RATEXP_AZURE_APP_URL=https://ratexp-dev-app.azurewebsites.net
pytest tests/test_azure_live.py
```
