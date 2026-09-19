# Proposed layout for `app/`

```
app/                                 THE DASHBOARD  (image: app)
│
├── api/                          ── the read-only HTTP surface
│   ├── serve_http.py                routes, CORS, the static UI mount, startup/shutdown
│   ├── record_schemas.py            Feedback, Transcript, QueryRequest
│   ├── build_snapshot.py            rows → models, and the feedback↔transcript matching
│   ├── trim_result_rows.py          newest-first, the view cap, the Download rule
│   └── broadcast_live.py            the /ws client set and the one broadcaster loop
│
├── modules/
│   └── read/                     ── get records back from the one chosen source
│       ├── open_read_source.py      reads config, builds the single enabled source
│       ├── connect_to_postgres.py   password / Entra connection modes
│       └── adapters/
│           ├── read_adapter_interface.py       what a source must implement
│           ├── read_from_postgres.py           shared SQL reading logic
│           ├── read_from_dynatrace.py          shared DQL reading logic
│           ├── read_from_app_be_psql.py        RateXp's own database
│           ├── read_from_custom_psql.py        an adopter's PostgreSQL
│           ├── read_from_app_be_dynatrace.py   RateXp's Dynatrace tenant
│           └── read_from_custom_dynatrace.py   an adopter's Dynatrace tenant
│
├── FE/                           ── the React dashboard
│   ├── index.html, vite.config.js, package.json, package-lock.json
│   ├── src/{App.jsx, main.jsx, index.css}
│   └── public/                      favicons, logo, og-image
│
├── tests/                        ── the app's own tests, mocked, no database
│   ├── conftest.py
│   ├── test_serve_http.py
│   ├── test_serve_http_query.py
│   ├── test_serve_http_cors.py
│   ├── test_build_snapshot.py
│   ├── test_broadcast_live.py
│   └── test_read_adapters.py
│
├── load_config.py                   reads config.yaml, fails loudly on a missing key
├── config.yaml                      limits, toggles, and which read source is on
├── .env.example                     credentials for the read source you switch on
├── Dockerfile                       stage 1 builds FE/, stage 2 runs the API
├── .dockerignore
├── pyproject.toml + uv.lock
└── README.md                        what it does, and every config key in one line
```
