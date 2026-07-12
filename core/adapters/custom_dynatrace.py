"""custom_dynatrace - an adopter's own Dynatrace tenant, over OpenTelemetry (OTLP).

See dynatrace.py for the shared OTLP export logic.
"""

from __future__ import annotations

from .dynatrace import DynatraceAdapter


class CustomDynatraceAdapter(DynatraceAdapter):
    def __init__(self, tenant_url: str, token: str) -> None:
        super().__init__("custom_dynatrace", tenant_url, token)
