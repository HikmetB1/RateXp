# ADR 0002: Each component builds on its own

- **Status:** Accepted
- **Scope:** core, app/ratexp and seeder, and the images of core and app/ratexp.

## Context: components that deploy separately

- **Separate deploys:** core, app/ratexp and seeder build, test and deploy separately. Each
  image builds from the folder of its component.
- **Shared needs:** core and app/ratexp both read the dashboard files and connect to the same
  PostgreSQL database. The core image serves the docs site, which comes from the doc pages of
  the whole repo.
- **The risk:** A shared code package ties the components together. A change for one
  component can then break the build of another component.

## Decision: own code for each component, data files through extra build contexts

- **Own code:** Each component keeps its own code. core and app/ratexp each keep their own copy
  of `clone_dashboard_from_base.py` and `connect_to_postgres.py`.
- **Data files from outside:** An image gets files from outside its folder only through an
  extra build context, and only data files:
  - **App image, context `dashboard`:** The app image copies `dashboard_base.yaml` and
    `dashboard_for_app.yaml` from `core/modules/dashboard/`. See
    [ADR 0001](./0001-one-panel-list-for-every-dashboard.md).
  - **Core image, context `repo`:** The core image copies the repo to build the docs site. The
    `.dockerignore` in the repo root keeps local files, caches and secrets out of the core
    image.
- **Build commands:** `docker-compose.yml` and the commands in
  [Deploy to Azure](../custom-deploy.md#deploy-to-azure-from-zero-to-live) pass the extra build
  contexts.

## Consequences: the checks and the steps after a change

- **Copies:** Change both copies in one commit. For `clone_dashboard_from_base.py`,
  `app/ratexp/tests/test_clone_dashboard_from_base.py` fails when the code differs. No test
  checks `connect_to_postgres.py`.
- **Plain `docker build`:** A plain `docker build` in the folder of core or app/ratexp fails,
  because the extra build context is missing. Use `docker-compose.yml` or the commands in
  Deploy to Azure.
- **After a change to the dashboard files:** Build the app image again.
- **After a change to a doc page:** Build the core image again, because the core image holds
  the docs site.
