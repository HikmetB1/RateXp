"""bluebox - a Bluebox workspace, over OpenTelemetry (OTLP).

Bluebox (by Dynatrace) provisions an OTLP ingest endpoint per workspace, so this
reuses the shared export logic in utils/dynatrace.py unchanged - same protobuf
transport, same ``Api-Token`` header, same record mapping. Nothing in that shared
file knows about Bluebox; the only difference lives here.

That difference is the URL. ``bluebox otlp-endpoint`` prints the endpoint with the
``/api/v2/otlp`` prefix already on it, while the base class expects a bare tenant
URL and appends the whole path itself. So strip the prefix when it is there and
let the base rebuild it - which also means a bare tenant URL works just as well,
and both forms land on the same endpoint instead of one of them silently 404ing.

Write-only. Bluebox has no read adapter because it deliberately exposes no raw
query language - you read it back by asking in plain English (``bluebox ask``),
which can't return the rows the dashboard's ReadAdapter contract needs.
"""

from __future__ import annotations

from .utils.dynatrace import DynatraceWriteAdapter

_OTLP_PREFIX = "/api/v2/otlp"


class BlueboxWriteAdapter(DynatraceWriteAdapter):
    def __init__(self, otlp_endpoint: str, token: str) -> None:
        tenant_url = otlp_endpoint.rstrip("/").removesuffix(_OTLP_PREFIX)
        super().__init__("bluebox", tenant_url, token)
