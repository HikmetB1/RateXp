"""app_be_dynatrace - RateXp's own Dynatrace tenant, over OpenTelemetry (OTLP).

See dynatrace.py for the shared OTLP export logic.
"""

from __future__ import annotations

from .dynatrace import DynatraceAdapter


class AppBeDynatraceAdapter(DynatraceAdapter):
    def __init__(self, tenant_url: str, token: str) -> None:
        super().__init__("app_be_dynatrace", tenant_url, token)
