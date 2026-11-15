# app/dynatrace

app/dynatrace is the RateXp Dynatrace app: the Dashboard view of the RateXp web app, built as
an app inside Dynatrace.

- **Not the Dynatrace dashboard:** core publishes the Dynatrace dashboard. The RateXp Dynatrace
  app is a separate app. You install the RateXp Dynatrace app on the tenant with
  `npm run deploy`.
- **Data:** The RateXp Dynatrace app reads the `ratexp.*` logs that core writes to Dynatrace.
- **Components:** Strato, the component library of Dynatrace, draws the RateXp Dynatrace app.
- **No token:** The RateXp Dynatrace app reads as the logged-in user. Thus, the RateXp
  Dynatrace app needs no token.

## Layout: what this folder holds

```text
app/dynatrace/
├── ui/app/
│   ├── pages/Dashboard.tsx   the filters, the timeframe, Download trajectories and the panel grid
│   ├── components/Panel.tsx  one panel: runs the DQL of the panel with useDql, and draws the panel by its kind
│   ├── components/TrajectoryDetails.tsx  the side panel that "view" in a Feedback row opens
│   └── dashboard/            dashboard.json (generated, see below) and the logic that the tests cover
├── scripts/sync-dashboard.mjs  writes dashboard.json from ../../core/modules/dashboard/
├── scripts/deploy-dev.mjs   deploys the dev copy of the RateXp Dynatrace app (npm run deploy:dev)
├── tests/                   vitest: filters, download, per-day series, environment, dashboard.json drift
└── app.config.json          the app id my.ratexp, the tenant, and the scopes that the RateXp Dynatrace app reads with
```

- **Generated file:** `ui/app/dashboard/dashboard.json` is the `dashboard_base.yaml` of core,
  cloned into `dashboard_for_dynatrace.yaml`, with `list_view_limit` and `list_max_limit` from
  `app/ratexp/config.yaml` filled in. The RateXp Dynatrace app cannot read the repo at
  runtime.
- **Update:** `npm start`, `npm run build` and `npm run deploy` first write `dashboard.json`
  again. `npm test` fails when `dashboard.json` is out of date.
- **Environment:** `dashboard.json` keeps the `{environment}` of the DQL. The RateXp Dynatrace
  app fills `{environment}` when the app starts, from its own app id: `dev` when the app id
  ends in `.dev`, else `prod`.

## Run locally: start the RateXp Dynatrace app on your machine

```bash
npm install && npm start
```

- **Browser:** `npm start` opens the RateXp Dynatrace app through your tenant in the browser,
  after you log in to Dynatrace.
- **VS Code:** The
  [Dynatrace Apps](https://marketplace.visualstudio.com/items?itemName=dynatrace.dynatrace-apps)
  VS Code extension can also run `npm install` and `npm start`.

## Config: every key in app.config.json

- `environmentUrl`: The apps host of the tenant that the RateXp Dynatrace app runs on.
- `app.id` / `app.name` / `app.version`: How the tenant lists the RateXp Dynatrace app. Each
  deploy needs a higher `version`.
- `app.scopes`: `storage:logs:read` and `storage:buckets:read`, to read the logs that core
  writes.

## Tests: how to run them

```bash
npm test && npm run lint
```

- **Offline:** The tests check the DQL as text. The tests do not run the DQL on the tenant.

## Deploy: how the RateXp Dynatrace app gets to Dynatrace

```bash
npm run deploy
```

- **Before you deploy:** Log in to the tenant with a user that has the right to install apps.
- **Result:** `npm run deploy` installs the RateXp Dynatrace app on `environmentUrl`.
- **Dev copy:** To install the dev copy next to the RateXp Dynatrace app, run this command:

  ```bash
  npm run deploy:dev
  ```

  - **App id:** The dev copy is `my.ratexp.dev`, named "RateXp (dev)". Thus, the dev copy never
    replaces `my.ratexp`.
  - **app.config.json:** `npm run deploy:dev` changes `app.config.json` for the deploy. Then
    `npm run deploy:dev` writes the old `app.config.json` back, also when the deploy fails.
