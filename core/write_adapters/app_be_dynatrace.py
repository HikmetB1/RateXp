"""app_be_dynatrace - RateXp's own Dynatrace tenant, over OpenTelemetry (OTLP).

See utils/dynatrace.py for the shared OTLP export logic.
"""

from __future__ import annotations

from .utils.dynatrace import DynatraceWriteAdapter


class AppBeDynatraceWriteAdapter(DynatraceWriteAdapter):
    def __init__(self, tenant_url: str, token: str) -> None:
        super().__init__("app_be_dynatrace", tenant_url, token)
