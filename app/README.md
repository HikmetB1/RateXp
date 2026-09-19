# app

## Config

Everything tunable lives in [`config.yaml`](./config.yaml), which explains each key inline:

- `schema_version`: ATIF version expected on stored transcripts (matches core's)
- `list_view_limit` / `list_max_limit`: rows the list endpoints return by default, and the
  hard ceiling on any one response
- `top_skills_limit`: how many skills the "Top skills" panel shows
- `query_enabled` / `query_timeout_ms` / `query_max_rows`: the filter box; `false` turns the
  endpoint off, the other two cap how long a query runs and how much it returns
- `ws_enabled` / `ws_broadcast_interval_ms`: the live feed; `false` turns it off, the interval
  is how often it checks for new data
- `read_adapters`: which single source the dashboard reads back from