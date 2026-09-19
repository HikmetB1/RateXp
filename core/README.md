# core

## Summary

`ratexp.sh` always posts to the same two core endpoints, `/feedback` and `/transcript`, and
never knows where the data ends up. Core is the admin: it decides which destinations are
switched on, and it does all the writing.

## Config

Everything tunable lives in [`config.yaml`](./config.yaml), which explains each key inline:

- `schema_version`: ATIF version stamped on every stored transcript
- `max_body_bytes` / `max_transcript_bytes`: largest request accepted, and largest trajectory
  stored in full (anything bigger keeps a meta-only stub)
- `rate_limit_per_minute`: per-IP budget; `0` turns the limiter off
- `default_survey_every`: ask on every Nth run, baked into the hook copies
- `redaction`: whether personal data is masked, and which adapter does it
- `write_adapters`: which destinations every submission is written to

## Hook copies

`GET /ratexp.sh` fills in the blanks in `ratexp.sh` per request. The copies under `template/`
and `examples/` are generated from it, so edits to a copy get wiped. Change `ratexp.sh`, then
regenerate:

```bash
python3 tools/sync_hooks.py          # regenerate the copies
python3 tools/sync_hooks.py --check  # report drift, change nothing (the tests run this)
```

A new template or example needs a line in `tools/sync_hooks.py`, or its copy keeps the blanks.
