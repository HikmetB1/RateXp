# ADR 0001: One panel list for every dashboard

- **Status:** Accepted
- **Scope:** The Dashboard view of the RateXp app, the Dynatrace dashboard and the RateXp
  Dynatrace app.

## Context: the same panels in three places

- **Three places:** The RateXp app shows the panels in its Dashboard view. Dynatrace shows the
  same panels in the Dynatrace dashboard and in the RateXp Dynatrace app.
- **Two query languages:** The RateXp app reads PostgreSQL with SQL. The Dynatrace dashboard
  and the RateXp Dynatrace app read the Dynatrace logs with DQL.
- **The risk:** If each place keeps its own list, the panels, their order and the filters drift
  apart.

## Decision: one shared base and one file for each platform

- **One folder:** All dashboard files are in
  [`core/modules/dashboard/`](../../core/modules/dashboard/).
- **One shared base:** `dashboard_base.yaml` lists the panels that each dashboard must have.
  Each panel has an id, a title and a kind (number, line, bar or table).
- **One file for each platform:** `dashboard_for_app.yaml` gives the SQL of each panel, and
  `dashboard_for_dynatrace.yaml` gives the DQL of each panel. Each file must contain all of
  the panels in `dashboard_base.yaml`.
- **Same panels and filters:** All dashboards show the same panels, in the same order, with
  the same filters.
- **Panel copy:** The RateXp Dynatrace app cannot read the repo at runtime. Thus,
  `app/dynatrace/scripts/sync-dashboard.mjs` copies `dashboard_for_dynatrace.yaml` into the
  `dashboard.json` file of the RateXp Dynatrace app.
- **Same row limits:** `list_view_limit` and `list_max_limit` set the rows of all dashboards.
  The RateXp app reads the two settings when it runs. `publish_to_dynatrace.py` and
  `sync-dashboard.mjs` write the two settings into the DQL when they publish or sync. See
  [Config and env](../config-and-env.md).

## Consequences: the checks, the steps after a change, and the differences

- **Missing panel:** If a platform file does not contain a base panel,
  `core/tests/test_clone_dashboard_from_base.py` fails.
- **Old panel copy:** If `dashboard.json` is not the same as `dashboard_for_dynatrace.yaml`,
  the tests of the RateXp Dynatrace app fail. `npm start`, `npm run build` and
  `npm run deploy` write `dashboard.json` again.
- **After a change to a panel or a row limit:**
  - **RateXp app:** Build and deploy the app image again.
  - **Dynatrace dashboard:** Run `publish_to_dynatrace.py` again.
  - **RateXp Dynatrace app:** Run `npm run deploy` again.
- **Differences that the platforms cause:**
  - **Dynatrace dashboard:** A Dynatrace dashboard has no buttons. Thus, the Dynatrace
    dashboard has no **Download trajectories** and no **Trajectory** column.
  - **Type is session:** The Dynatrace dashboard cannot hide the Skill filter or mark a panel
    "Does not apply". There, Skill shows only "(none)", and **Skills rated** shows
    "n/a: session". The RateXp app and the RateXp Dynatrace app hide the Skill filter.
