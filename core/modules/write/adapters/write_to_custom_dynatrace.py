"""custom_dynatrace - an adopter's own Dynatrace tenant, over OpenTelemetry (OTLP).

See write_to_dynatrace.py for the shared OTLP export logic.
"""

from __future__ import annotations

from modules.write.adapters.write_to_dynatrace import DynatraceWriteAdapter


class CustomDynatraceWriteAdapter(DynatraceWriteAdapter):
    def __init__(self, tenant_url: str, token: str) -> None:
        super().__init__("custom_dynatrace", tenant_url, token)
