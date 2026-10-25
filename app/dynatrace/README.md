# app/dynatrace

app/dynatrace is the RateXp web app's Dashboard view as a Dynatrace app, drawn with Strato,
Dynatrace's own components. It reads the `ratexp.*` logs core writes to Dynatrace, as the
logged-in user, so it needs no token of its own.

## Layout: what lives in this folder

```text
app/dynatrace/
├── ui/app/
│   ├── pages/Dashboard.tsx   the filters, timeframe, Download trajectories and the panel grid
│   ├── components/Panel.tsx  one panel: its DQL run with useDql, drawn by its kind
│   └── dashboard/            dashboard.json (generated, see below) and the logic the tests cover
├── scripts/sync-dashboard.mjs  writes dashboard.json from ../../core/modules/dashboard/
├── tests/                   vitest: filters, download, per-day series, dashboard.json drift
└── app.config.json          app id my.ratexp, the tenant, and the scopes it reads with
```

`ui/app/dashboard/dashboard.json` is core's `dashboard_base.yaml` cloned into
`dashboard_for_dynatrace.yaml`, since an app cannot read the repo at runtime. `npm start`,
`npm run build` and `npm run deploy` rewrite it first; `npm test` fails while it is stale.

## Running locally: start it on your machine

```bash
npm install && npm start
```

This opens the app through your tenant in the browser, after a Dynatrace login. The
[Dynatrace Apps](https://marketplace.visualstudio.com/items?itemName=dynatrace.dynatrace-apps)
VS Code extension runs the same commands.

## Config: every key in app.config.json

- `environmentUrl`: the tenant's apps host the app runs against
- `app.id` / `app.name` / `app.version`: how the tenant lists the app; a deploy needs a higher
  `version` each time
- `app.scopes`: `storage:logs:read` and `storage:buckets:read`, for the logs core writes

## Tests: how to run them

```bash
npm test && npm run lint
```

Offline: the DQL is checked as text, not run against the tenant.

## Deploy: how it gets to Dynatrace

```bash
npm run deploy
```

This installs the app on `environmentUrl`, once you have logged in to the tenant with the
right to install apps.
