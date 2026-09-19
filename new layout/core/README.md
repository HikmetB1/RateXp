```
core/
├── Dockerfile
├── pyproject.toml
├── uv.lock
├── config.yaml
├── load_config.py
├── ratexp.sh
├── api/
│   ├── serve_http.py
│   ├── record_schemas.py
│   ├── build_trajectory.py
│   ├── ingest_records.py
│   └── limit_request_rate.py
├── modules/
│   ├── redaction/
│   │   ├── redact_trajectory.py
│   │   └── adapters/
│   │       ├── redactor_interface.py
│   │       ├── redact_with_presidio.py
│   │       └── redact_with_azure.py
│   └── write/
│       ├── dispatch_to_adapters.py
│       ├── connect_to_postgres.py
│       ├── adapters/
│       │   ├── write_adapter_interface.py
│       │   ├── write_to_postgres.py
│       │   └── write_to_dynatrace.py
│       └── schema/
│           ├── apply_migrations.py
│           ├── 001_create_feedback_table.sql
│           └── 002_create_transcript_table.sql
└── tests/
```
