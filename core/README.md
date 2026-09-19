# core

`api/` and `modules/` carry no `__init__.py`. They resolve only with `core/` itself on
`sys.path`: the image gets that from `WORKDIR /app` (Dockerfile), the tests from
`tests/conftest.py`. Import from that root every time —
`from modules.write import dispatch_to_adapters` — or a module loads a second time
under a second name, and the singletons it holds (`_adapters`, `_redactor`) split in two.

`ratexp.sh` is the canonical hook and ships with its settings unresolved: `GET
/ratexp.sh` substitutes `'__RATEXP_URL__'` and `'__RATEXP_EVERY__'` per request. The
copies under `template/` and `examples/` are generated from it by
`scripts/sync-hooks.py`, which the tests here check — edit a copy and the next run
overwrites it.

Running the tests: see [CONTRIBUTING](../CONTRIBUTING.md#tests).
