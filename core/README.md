# core

`ratexp.sh` always posts to the same two core endpoints, `/feedback` and `/transcript`, and
never knows where the data ends up. Core is the admin: it does all the writing, and you set
where it writes (`write_adapters`) and how personal data is masked (`redaction`) in `config.yaml`.

Nothing here has an `__init__.py`, so `api/` and `modules/` only import with `core/` as the
starting point — `WORKDIR /app` in the container, `tests/conftest.py` in the tests. Import
the full path, like `from modules.write import dispatch_to_adapters`, or the same file can
load twice under two names.

`GET /ratexp.sh` fills in the blanks in `ratexp.sh` on each request; `sync_hooks.py` writes
the filled-in copies into `template/` and `examples/`, so edits to a copy get wiped. A new
template or example needs a line in `sync_hooks.py`, or its copy keeps the blanks.

Tests: see [CONTRIBUTING](../CONTRIBUTING.md#tests).
